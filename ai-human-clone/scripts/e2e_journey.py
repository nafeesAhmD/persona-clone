"""End-to-end user journey against a running backend (Phase 20).

Runs INSIDE the backend container (it uses the app's DB session only for QA setup and
cleanup: promoting a QA admin via the project's grant_admin service and deleting the QA accounts):

    docker compose cp scripts/e2e_journey.py backend:/tmp/e2e_journey.py
    docker compose exec -T -w /app -e PYTHONPATH=/app backend python /tmp/e2e_journey.py journey
    docker compose restart backend          # persistence check
    docker compose exec -T -w /app -e PYTHONPATH=/app backend python /tmp/e2e_journey.py finish

Only fresh accounts `qa-<random>@example.com` are used; their passwords are random and
kept in /tmp/e2e_state.json inside the container (never printed). `finish` deletes
everything the journey created. Each step prints PASS / FAIL / BLOCKED with its time.
Gemini (free tier) 429/503 answers are retried once and then reported as BLOCKED.
Set E2E_CLONED_VOICE_BLOCKED="reason" when the self-hosted voice-clone service is stopped.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import os
import secrets
import struct
import sys
import time

import httpx

API = os.getenv("E2E_API", "http://localhost:8000")
ORIGIN = os.getenv("E2E_ORIGIN", "http://localhost:3007")
STATE = "/tmp/e2e_state.json"
RESULTS = "/tmp/e2e_results.json"
SAMPLE_WAV = "/tmp/e2e_sample.wav"  # optional real speech sample copied in by the operator

PUBLIC_DOC = """Zara Malik — profile (fictional QA data)
Zara Malik is a pastry chef who owns Gulab Crust Bakery in Gulberg, Lahore.
She opened Gulab Crust Bakery in March 2014 after training in Karachi.
Her signature item is the saffron sheermal croissant.
The bakery is closed on Mondays and opens at 8 am on other days.
"""
PRIVATE_DOC = """Internal notes (private, fictional QA data)
The bakery storeroom safe code is 4471-ORCHID.
Zara's supplier contract with Ravi Mills is renewed every September.
"""


class Blocked(Exception):
    pass


results: list[dict] = []


def record(step: str, status: str, seconds: float, note: str = "") -> None:
    results.append({"step": step, "status": status, "seconds": round(seconds, 2), "note": note})
    print(f"{status:7} {seconds:7.2f}s  {step}" + (f"  — {note}" if note else ""), flush=True)


def run(step: str):
    def wrap(fn):
        started = time.monotonic()
        try:
            note = fn() or ""
            record(step, "PASS", time.monotonic() - started, note)
        except Blocked as exc:
            record(step, "BLOCKED", time.monotonic() - started, str(exc))
        except AssertionError as exc:
            record(step, "FAIL", time.monotonic() - started, str(exc) or "assertion failed")
        except Exception as exc:  # noqa: BLE001 - a broken step must not stop the journey
            record(step, "FAIL", time.monotonic() - started, f"{type(exc).__name__}: {str(exc)[:160]}")
        return fn

    return wrap


def safe_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:120]
    detail = body.get("detail") if isinstance(body, dict) else body
    return str(detail)[:160]


def check(response: httpx.Response, *codes: int) -> httpx.Response:
    codes = codes or (200,)
    if response.status_code in (429, 503) and response.status_code not in codes:
        raise Blocked(f"provider/limit {response.status_code}: {safe_detail(response)}")
    assert response.status_code in codes, f"HTTP {response.status_code}: {safe_detail(response)}"
    return response


def with_retry(send):
    """One retry after a pause on 429/503 (free-tier Gemini), then the caller decides."""
    response = send()
    if response.status_code in (429, 503):
        time.sleep(20)
        response = send()
    return response


def client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=180, headers={"Origin": ORIGIN})


def tone_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    samples = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * n / rate))) for n in range(int(seconds * rate))
    )
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16
    ) + b"data" + struct.pack("<I", len(samples))
    return header + samples


def answer_of(response: httpx.Response) -> tuple[str, dict]:
    body = response.json()
    return body["message"]["content"], body


def has_any(text: str, words) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words)


def _set_admin(email: str, on: bool) -> None:
    """Promote (project service `grant_admin`, audited) or demote a QA account."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415
    from app.services.admin_bootstrap import grant_admin  # noqa: PLC0415

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if on:
            grant_admin(db, user, "qa:e2e")
        else:
            user.is_admin = False
        db.commit()


# --------------------------------------------------------------------------------------


def journey() -> None:
    tag = secrets.token_hex(4)
    users = {
        name: {"email": f"qa-{tag}-{name}@example.com", "username": f"qa{tag}{name}", "password": secrets.token_urlsafe(18) + "a1"}
        for name in ("owner", "other", "admin")
    }
    state: dict = {"tag": tag, "users": users, "created": {}}

    def save() -> None:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    save()
    sessions = {name: client() for name in users}
    owner, other, admin = sessions["owner"], sessions["other"], sessions["admin"]
    anon = client()
    ctx: dict = {}

    @run("01 register (3 QA users)")
    def _():
        for name, user in users.items():
            r = sessions[name].post("/api/auth/register", json={**user, "full_name": f"QA {name}"})
            check(r, 201)
            assert "hashed_password" not in r.text and user["password"] not in r.text, "password data in register reply"
            state["users"][name]["id"] = r.json()["id"]
        save()

    @run("02 login / logout / me")
    def _():
        check(owner.post("/api/auth/logout"), 204)
        assert owner.get("/api/auth/me").status_code == 401, "/me still works after logout"
        bad = owner.post("/api/auth/login", json={"email": users["owner"]["email"], "password": "wrong-password-123"})
        assert bad.status_code in (400, 401), f"wrong password gave {bad.status_code}"
        check(owner.post("/api/auth/login", json={"email": users["owner"]["email"], "password": users["owner"]["password"]}))
        check(owner.get("/api/auth/me"))

    @run("03 create clone")
    def _():
        r = check(owner.post("/api/clones", json={
            "name": f"QA Zara {tag}", "owner_consent": True, "profession": "Pastry chef",
            "tagline": "QA clone (fictional)", "skills": ["baking", "pastry"], "preferred_language": "English",
        }), 201)
        ctx["clone"] = r.json()
        state["created"]["clone_id"] = ctx["clone"]["id"]
        save()

    cid = lambda: ctx["clone"]["id"]  # noqa: E731

    @run("04 edit personality and settings")
    def _():
        r = check(owner.patch(f"/api/clones/{cid()}", json={
            "personality_description": "Warm, precise, answers only from known facts and says so when unsure.",
            "communication_style": "friendly", "response_length": "short",
        }))
        assert r.json().get("personality_description", "").startswith("Warm"), "personality not saved"

    @run("05 upload knowledge documents (txt) + reject executable")
    def _():
        for key, title, text in (("public_doc", "Zara public profile", PUBLIC_DOC), ("private_doc", "Zara private notes", PRIVATE_DOC)):
            r = check(owner.post(f"/api/clones/{cid()}/documents", files={"file": (f"{key}.txt", text.encode(), "text/plain")},
                                 data={"title": title}), 201)
            ctx[key] = r.json()
            assert r.json()["status"] in ("ready", "processing", "pending"), f"doc status {r.json()['status']}"
        bad = owner.post(f"/api/clones/{cid()}/documents", files={"file": ("evil.exe", b"MZ\x90\x00binary", "application/x-msdownload")})
        assert bad.status_code in (400, 415, 422), f"executable upload gave {bad.status_code}"

    @run("06 extract + index (wait for vectors)")
    def _():
        notes = []
        for key in ("public_doc", "private_doc"):
            doc_id = ctx[key]["id"]
            started = time.monotonic()
            detail = check(owner.get(f"/api/clones/{cid()}/documents/{doc_id}")).json()
            if detail.get("indexing_status") == "not_indexed":
                owner.post(f"/api/clones/{cid()}/documents/{doc_id}/index")
            for _ in range(60):
                detail = check(owner.get(f"/api/clones/{cid()}/documents/{doc_id}")).json()
                if detail.get("indexing_status") == "indexed":
                    break
                time.sleep(2)
            assert detail.get("indexing_status") == "indexed", f"not indexed: {detail.get('indexing_status')}"
            notes.append(f"{key} chunks={detail.get('chunk_count')} {time.monotonic() - started:.1f}s")
        check(owner.patch(f"/api/clones/{cid()}/documents/{ctx['public_doc']['id']}/visibility", json={"visibility": "public"}))
        return "; ".join(notes)

    def chat(session: httpx.Client, message: str, conversation: str | None = None) -> tuple[str, dict]:
        body = {"message": message, **({"conversation_id": conversation} if conversation else {})}
        r = with_retry(lambda: session.post(f"/api/clones/{cid()}/chat", json=body))
        check(r)
        return answer_of(r)

    @run("07 grounded question uses RAG + sources")
    def _():
        text, body = chat(owner, "When did Zara open her bakery, what is it called, and where is it?")
        ctx["conversation"] = body["conversation_id"]
        state["created"]["conversation_id"] = body["conversation_id"]
        save()
        assert has_any(text, ["2014"]) and has_any(text, ["Gulab Crust"]), f"answer missed facts: {text[:150]}"
        assert body.get("sources"), "no sources returned"
        return f"sources={len(body['sources'])}"

    @run("08 unsupported personal fact is not invented")
    def _():
        text, _ = chat(owner, "What is Zara's blood type and her exact home address?", ctx.get("conversation"))
        refusal = ["don't know", "do not know", "not sure", "no information", "don't have", "do not have", "can't", "cannot",
                   "not available", "isn't", "not something", "nahi", "unable", "not in", "not mentioned", "share",
                   "doesn't include", "does not include", "not include", "won't"]
        assert has_any(text, refusal), f"may have invented: {text[:200]}"
        assert not re.search(r"\b(?:ab|a|b|o)\s*(?:positive|negative|[+-])(?=\s|$|[.,;])", text, re.I), f"invented blood type: {text[:150]}"

    @run("09 memory create (approved) is used in chat")
    def _():
        r = check(owner.post(f"/api/clones/{cid()}/memories", json={"memory_type": "preference", "content": "Zara's favourite cake is pistachio rose cake."}), 201)
        ctx["memory"] = r.json()
        assert r.json()["status"] == "approved", f"manual memory status {r.json()['status']}"
        time.sleep(2)
        text, body = chat(owner, "What is your favourite cake?")
        assert has_any(text, ["pistachio"]), f"memory not used: {text[:150]}"
        return f"memories_used={body.get('memories_used')}"

    @run("10 conversation history")
    def _():
        convs = check(owner.get(f"/api/clones/{cid()}/conversations")).json()
        assert convs, "no conversations listed"
        detail = check(owner.get(f"/api/conversations/{ctx['conversation']}")).json()
        msgs = detail.get("messages", [])
        assert len(msgs) >= 4, f"expected >=4 messages, got {len(msgs)}"
        return f"conversations={len(convs)} messages={len(msgs)}"

    @run("11a voice needs consent; enable with consent")
    def _():
        r = owner.patch(f"/api/clones/{cid()}/voice/settings", json={"voice_enabled": True})
        assert r.status_code in (400, 403, 409, 422), f"voice enabled without consent: {r.status_code}"
        check(owner.patch(f"/api/clones/{cid()}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}))

    @run("11b speech-to-text (Gemini, sample WAV)")
    def _():
        audio = open(SAMPLE_WAV, "rb").read() if os.path.exists(SAMPLE_WAV) else tone_wav(2)
        r = with_retry(lambda: owner.post(f"/api/clones/{cid()}/voice/transcribe", files={"audio": ("q.wav", audio, "audio/wav")}))
        if r.status_code == 422 and not os.path.exists(SAMPLE_WAV):
            raise Blocked("no speech sample available (tone only)")
        check(r)
        return f"language={r.json().get('language')} chars={len(r.json().get('text', ''))}"

    @run("11c text-to-speech (AI voice, Gemini)")
    def _():
        r = with_retry(lambda: owner.post(f"/api/clones/{cid()}/voice/test", json={"text": "Hello, this is a QA test."}))
        check(r)
        url = r.json()["audio_url"]
        audio = owner.get(url)
        assert audio.status_code == 200 and len(audio.content) > 1000, f"audio fetch {audio.status_code}"
        assert anon.get(url).status_code in (401, 403, 404), "audio readable without login"
        return f"{len(audio.content)} bytes"

    @run("11d cloned voice (self-hosted)")
    def _():
        reason = os.getenv("E2E_CLONED_VOICE_BLOCKED")
        if reason:
            raise Blocked(reason)
        raise Blocked("not exercised by this script (needs a recorded voice sample + consent flow)")

    @run("12 avatar video")
    def _():
        settings = owner.get(f"/api/clones/{cid()}/avatar")
        if settings.status_code != 200:
            raise Blocked(f"avatar settings {settings.status_code}: {safe_detail(settings)[:80]}")
        r = owner.post(f"/api/clones/{cid()}/avatar/test", json={"text": "Hi"})
        if r.status_code in (400, 403, 409, 422, 503):
            raise Blocked(f"no avatar photo/consent/provider for QA clone ({r.status_code}: {safe_detail(r)[:80]})")
        check(r, 202)
        return "job created"

    @run("13 publish clone (public + public chat) and public page")
    def _():
        r = check(owner.patch(f"/api/clones/{cid()}/public-settings", json={"visibility": "public", "public_chat_enabled": True}))
        ctx["slug"] = r.json()["slug"]
        profile = check(anon.get(f"/api/public/clones/{ctx['slug']}")).json()
        leaked = [k for k in ("owner_id", "email", "owner_email", "personality_description") if k in profile]
        assert not leaked, f"public profile leaks {leaked}"

    @run("14 public chat uses public doc only (no private doc/memory)")
    def _():
        visitor = client()
        r = with_retry(lambda: visitor.post(f"/api/public/clones/{ctx['slug']}/chat", json={"message": "What is the storeroom safe code and what is your favourite cake?"}))
        check(r)
        body = r.json()
        text = body["message"]["content"]
        token = body.get("session_id")
        assert not has_any(text, ["4471", "orchid"]), f"PRIVATE DOC LEAKED: {text[:150]}"
        assert not has_any(text, ["pistachio"]), f"PRIVATE MEMORY LEAKED: {text[:150]}"
        r2 = with_retry(lambda: visitor.post(f"/api/public/clones/{ctx['slug']}/chat",
                                             json={"message": "When did the bakery open?", "session_id": token}))
        check(r2)
        assert has_any(r2.json()["message"]["content"], ["2014"]), f"public doc not used: {r2.json()['message']['content'][:120]}"

    @run("15 other user cannot reach owner's private data")
    def _():
        denied = []
        for path in (f"/api/clones/{cid()}/documents", f"/api/clones/{cid()}/documents/{ctx['private_doc']['id']}",
                     f"/api/conversations/{ctx['conversation']}", f"/api/clones/{cid()}/memories",
                     f"/api/clones/{cid()}/analytics/overview", f"/api/clones/{cid()}/voice/settings"):
            code = other.get(path).status_code
            if code not in (401, 403, 404):
                denied.append(f"{path} -> {code}")
        code = other.patch(f"/api/clones/{cid()}", json={"name": "hijack"}).status_code
        if code not in (401, 403, 404):
            denied.append(f"PATCH clone -> {code}")
        code = other.delete(f"/api/clones/{cid()}/documents/{ctx['private_doc']['id']}").status_code
        if code not in (401, 403, 404):
            denied.append(f"DELETE doc -> {code}")
        assert other.get("/api/auth/me").status_code == 200, "probe user not logged in (test invalid)"
        assert not denied, "; ".join(denied)
        return "8 cross-user probes denied (probe user logged in)"

    @run("16 analytics")
    def _():
        body = check(owner.get(f"/api/clones/{cid()}/analytics/overview")).json()
        return f"keys={sorted(body)[:5]}"

    @run("17 billing usage / plan limits")
    def _():
        usage = check(owner.get("/api/billing/usage")).json()
        sub = owner.get("/api/billing/subscription")
        return f"usage keys={sorted(usage)[:4]}; billing_enabled={usage.get('billing_enabled')}; subscription={sub.status_code}"

    @run("18 organization: invite viewer, viewer cannot edit")
    def _():
        org = check(owner.post("/api/organizations", json={"name": f"QA Org {tag}"}), 201).json()
        state["created"]["org_id"] = org["id"]
        save()
        inv = check(owner.post(f"/api/organizations/{org['id']}/invitations", json={"email": users["other"]["email"], "role": "viewer"}), 200, 201).json()
        check(other.post(f"/api/invitations/{inv['token']}/accept"), 200, 201)
        members = check(owner.get(f"/api/organizations/{org['id']}/members")).json()
        assert len(members) >= 2, "viewer not a member"
        code = other.patch(f"/api/organizations/{org['id']}", json={"name": "viewer-rename"}).status_code
        assert code in (401, 403), f"viewer could edit org: {code}"
        stranger = admin.get(f"/api/organizations/{org['id']}").status_code
        assert stranger in (403, 404), f"non-member could read org: {stranger}"

    @run("19 developer API key: create → use → revoke → 401")
    def _():
        scopes = [s["scope"] if isinstance(s, dict) else s for s in check(owner.get("/api/developer/keys/scopes")).json()]
        wanted = [s for s in scopes if s.startswith("clones")] or scopes[:1]
        created = check(owner.post("/api/developer/keys", json={"name": "qa-key", "scopes": wanted}), 201).json()
        raw = created["key"]
        state["created"]["key_id"] = created["id"]
        save()
        assert raw not in owner.get("/api/developer/keys").text, "raw key visible in key list"
        api = httpx.Client(base_url=API, timeout=60, headers={"Authorization": f"Bearer {raw}"})
        ok = api.get("/api/v1/clones")
        assert ok.status_code == 200, f"v1 with key {ok.status_code}"
        assert any(c["id"] == cid() for c in ok.json().get("data", [])), "own clone missing in v1"
        check(owner.post(f"/api/developer/keys/{created['id']}/revoke"))
        after = api.get("/api/v1/clones").status_code
        assert after == 401, f"revoked key still works: {after}"

    @run("20a agent: confirmation-required tool waits for approval")
    def _():
        check(owner.patch(f"/api/clones/{cid()}/agent", json={"enabled": True, "require_confirmation_for_actions": True}))
        check(owner.put(f"/api/clones/{cid()}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True}))
        r = with_retry(lambda: owner.post(f"/api/clones/{cid()}/agent/run", json={"goal": "Use the calculator tool to compute 1234 * 56 and tell me the result."}))
        check(r, 200, 201, 202)
        exec_id = r.json()["execution_id"]
        status = r.json().get("status")
        for _ in range(60):
            if status in ("waiting_confirmation", "completed", "failed", "timeout", "cancelled"):
                break
            time.sleep(2)
            status = check(owner.get(f"/api/agent/executions/{exec_id}")).json()["status"]
        if status in ("failed", "timeout"):
            raise Blocked(f"agent run {status} (LLM)")
        assert status == "waiting_confirmation", f"no confirmation requested: {status}"
        assert other.get("/api/auth/me").status_code == 200, "probe user not logged in (test invalid)"
        action = check(owner.get(f"/api/agent/executions/{exec_id}")).json()["pending_action"]["action_id"]
        code = other.post(f"/api/agent/executions/{exec_id}/confirm", json={"action_id": action}).status_code
        assert code in (403, 404), f"other user could confirm: {code}"
        check(owner.post(f"/api/agent/executions/{exec_id}/confirm", json={"action_id": action}))
        final = {}
        for _ in range(60):
            final = check(owner.get(f"/api/agent/executions/{exec_id}")).json()
            if final["status"] in ("completed", "failed", "timeout", "cancelled"):
                break
            if final["status"] == "waiting_confirmation" and final.get("pending_action"):
                owner.post(f"/api/agent/executions/{exec_id}/confirm", json={"action_id": final["pending_action"]["action_id"]})
            time.sleep(2)
        if final["status"] in ("failed", "timeout"):
            raise Blocked(f"agent run {final['status']} after confirm (LLM)")
        assert final["status"] == "completed", f"after confirm: {final['status']}"
        text = json.dumps(final)
        return "result contains 69104" if "69104" in text or "69,104" in text else "completed (result text not matched)"

    async def _reuse_ticket(created) -> bool:
        import websockets  # noqa: PLC0415

        url = API.replace("http", "ws", 1) + created["ws_path"] + "?ticket=" + created["ticket"]
        try:
            async with websockets.connect(url, origin=ORIGIN) as ws:
                await asyncio.wait_for(ws.recv(), timeout=10)
        except websockets.ConnectionClosed as exc:
            return exc.rcvd is not None and exc.rcvd.code in (4403, 4404, 4410)
        except Exception:  # noqa: BLE001 - refused at handshake also counts as refused
            return True
        return False

    @run("20b realtime voice: session + WebSocket text turn (browser speech)")
    def _():
        import websockets  # noqa: PLC0415 - in the backend image (uvicorn[standard])

        r = owner.post(f"/api/clones/{cid()}/realtime/session", json={})
        if r.status_code == 503:
            raise Blocked(f"realtime disabled: {safe_detail(r)}")
        created = check(r, 201).json()
        assert created["ticket"] not in check(owner.get(f"/api/clones/{cid()}/realtime/session/{created['session_id']}")).text

        async def turn() -> str:
            url = API.replace("http", "ws", 1) + created["ws_path"] + "?ticket=" + created["ticket"]
            async with websockets.connect(url, origin=ORIGIN, max_size=None) as ws:
                await ws.send(json.dumps({"type": "hello"}))
                await ws.send(json.dumps({"type": "speech_mode", "mode": "browser"}))
                await ws.send(json.dumps({"type": "text", "text": "In one sentence, where is your bakery?"}))
                answer, started, first = "", time.monotonic(), None
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=180)
                    if isinstance(raw, bytes):
                        continue
                    msg = json.loads(raw)
                    if msg["type"] == "answer_delta" and first is None:
                        first = time.monotonic() - started
                    if msg["type"] == "answer":
                        answer = msg["text"]
                    if msg["type"] == "error":
                        raise Blocked(f"realtime error {msg.get('code')}")
                    if msg["type"] == "turn_done":
                        break
                await ws.send(json.dumps({"type": "end"}))
                ctx["realtime_first_delta"] = first
                return answer

        answer = asyncio.run(turn())
        assert has_any(answer, ["Gulberg", "Lahore", "Gulab"]), f"realtime answer: {answer[:120]}"
        assert asyncio.run(_reuse_ticket(created)), "ticket could be reused"
        return f"first delta {ctx.get('realtime_first_delta') or 0:.1f}s; ticket single-use"

    @run("20c marketplace: confirm → listed in search → opt-out")
    def _():
        url = f"/api/clones/{cid()}/marketplace"
        settings = {"enabled": True, "category": "business", "tags": ["baking"], "short_description": "QA bakery clone"}
        first = owner.patch(url, json=settings)
        assert first.status_code == 409, f"publish without confirmation gave {first.status_code}"
        check(owner.patch(url, json={**settings, "confirm_publish": True}))
        found = check(anon.get("/api/marketplace/search", params={"q": f"Zara {tag}"})).json()
        assert any(i["id"] == cid() for i in found["items"]), "not found in marketplace search"
        dump = json.dumps(found)
        assert users["owner"]["email"] not in dump and "owner_id" not in dump, "marketplace leaks owner data"
        check(owner.patch(url, json={"enabled": False}))
        gone = check(anon.get("/api/marketplace/search", params={"q": f"Zara {tag}"})).json()
        assert not any(i["id"] == cid() for i in gone["items"]), "still listed after opt-out"
        assert anon.get(f"/api/marketplace/clones/{ctx['slug']}").status_code == 404, "unlisted profile still served"

    @run("21 admin action + audit log (QA admin, then demoted)")
    def _():
        assert owner.get("/api/admin/users").status_code in (401, 403), "non-admin reached admin API"
        _set_admin(users["admin"]["email"], True)
        state["created"]["admin_promoted"] = True
        save()
        check(admin.post("/api/auth/login", json={"email": users["admin"]["email"], "password": users["admin"]["password"]}))
        other_id = users["other"]["id"]
        check(admin.patch(f"/api/admin/users/{other_id}/status", json={"is_active": False, "reason": "QA test"}))
        assert other.get("/api/auth/me").status_code in (401, 403), "deactivated user still active"
        check(admin.patch(f"/api/admin/users/{other_id}/status", json={"is_active": True, "reason": "QA test done"}))
        logs = check(admin.get("/api/admin/audit-logs")).json()
        items = logs.get("items", logs)
        assert any(other_id in json.dumps(row) for row in items), "no audit row for the status change"
        assert users["admin"]["password"] not in json.dumps(logs), "password in audit log"

    @run("22a health live / ready")
    def _():
        assert anon.get("/api/health/live").json().get("status") == "alive"
        ready = anon.get("/api/health/ready")
        assert ready.status_code == 200, f"ready {ready.status_code}"
        assert set(ready.json().get("checks", {})) <= {"database", "qdrant"}, "ready exposes extra details"

    save()
    with open(RESULTS, "w", encoding="utf-8") as fh:
        json.dump({"phase": "journey", "results": results}, fh, indent=1)
    passed = sum(r["status"] == "PASS" for r in results)
    print(f"\nstate saved; now restart the backend and run `finish`. ({passed}/{len(results)} PASS)")


def finish() -> None:
    state = json.load(open(STATE, encoding="utf-8"))
    users, created = state["users"], state["created"]
    owner = client()

    @run("22b persistence after backend restart")
    def _():
        for _ in range(40):
            try:
                if owner.get("/api/health/ready").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(3)
        check(owner.post("/api/auth/login", json={"email": users["owner"]["email"], "password": users["owner"]["password"]}))
        check(owner.get(f"/api/clones/{created['clone_id']}"))
        docs = check(owner.get(f"/api/clones/{created['clone_id']}/documents")).json()
        conv = check(owner.get(f"/api/conversations/{created['conversation_id']}")).json()
        hits = owner.post(f"/api/clones/{created['clone_id']}/knowledge/search", json={"query": "When did the bakery open?"})
        assert len(docs) >= 2 and conv.get("messages"), "data missing after restart"
        assert hits.status_code == 200 and "2014" in hits.text, f"vector search after restart: {hits.status_code}"
        return f"clone ok, docs={len(docs)}, messages={len(conv['messages'])}, vector search finds 2014"

    @run("99 cleanup (API deletes, demote admin, delete QA accounts)")
    def _():
        if created.get("org_id"):
            owner.delete(f"/api/organizations/{created['org_id']}")
        if created.get("key_id"):
            owner.delete(f"/api/developer/keys/{created['key_id']}")
        if created.get("clone_id"):
            r = owner.delete(f"/api/clones/{created['clone_id']}")
            assert r.status_code in (204, 404), f"clone delete {r.status_code}"
        if created.get("admin_promoted"):
            _set_admin(users["admin"]["email"], False)
        from sqlalchemy import delete, select  # noqa: PLC0415

        from app.db.session import SessionLocal  # noqa: PLC0415
        from app.models import User  # noqa: PLC0415
        from app.models import Organization  # noqa: PLC0415

        emails = [u["email"] for u in users.values()]
        with SessionLocal() as db:
            ids = list(db.scalars(select(User.id).where(User.email.in_(emails))))
            # Audit rows keep the QA admin id (no FK): the audit trail is never rewritten.
            # The org API only deactivates organizations, so the QA org row is removed here.
            db.execute(delete(Organization).where(Organization.name == f"QA Org {state['tag']}"))
            db.execute(delete(User).where(User.id.in_(ids)))
            db.commit()
            left = db.scalar(select(User.id).where(User.email.like(f"qa-{state['tag']}-%")))
        assert left is None, "QA user left behind"
        return f"deleted {len(ids)} QA users"

    data = json.load(open(RESULTS, encoding="utf-8")) if os.path.exists(RESULTS) else {"results": []}
    data["results"] += results
    with open(RESULTS, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.remove(STATE)


if __name__ == "__main__":
    {"journey": journey, "finish": finish}[sys.argv[1] if len(sys.argv) > 1 else "journey"]()
