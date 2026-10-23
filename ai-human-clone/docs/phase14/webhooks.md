# Webhooks

Webhooks let your app hear about things that happen in AI Human Clone (a clone was
created, a chat answer finished, a video rendered) without polling. You register an
HTTPS URL; we POST a signed JSON event to it.

Manage webhooks in the Developer area (`/developer`) or through the management API
under `/api/developer/webhooks` (logged-in session).

## Events

| Event | When |
| --- | --- |
| `clone.created` | A clone was created. |
| `clone.updated` | A clone's settings were changed. |
| `conversation.created` | Someone started a new conversation with a clone. |
| `message.completed` | A clone finished an answer (chat, streaming or voice). |
| `voice.completed` | A voice chat turn finished (transcription, answer and speech). |
| `avatar.completed` | A talking-avatar video finished rendering. |
| `usage.limit_reached` | A monthly developer API limit was reached (sent at most once an hour per limit). |
| `subscription.updated` | A subscription's status changed. |
| `webhook.test` | Only sent by "Send test event"; can't be subscribed to. |

Personal webhooks receive events for your own clones and account. Organization
webhooks (created by an organization owner or admin) receive events for clones
assigned to that organization. Event data contains **ids, types, counts and statuses
only** - never message text, prompts, transcripts, documents, secrets or file paths.
Fetch the content you need through the developer API with your API key.

## Payload

```http
POST /your/webhook HTTP/1.1
Content-Type: application/json
User-Agent: AHC-Webhooks/1.0
X-AHC-Event-Id: evt_Jk3n9Q2xY7bLm0Pq1Rs4tUv5
X-AHC-Event-Type: message.completed
X-AHC-Signature: t=1791200000,v1=5f2b0c...e91a

{"data":{"clone_id":"6f1c...","conversation_id":"a2d4...","input_mode":"text","latency_ms":812,
"memories_used":1,"message_id":"c93e...","model":"gpt-4o-mini","role":"assistant","sources_count":2,
"streamed":false},"id":"evt_Jk3n9Q2xY7bLm0Pq1Rs4tUv5","timestamp":"2026-10-05T09:13:20Z",
"type":"message.completed"}
```

The envelope is always:

```json
{
  "id": "evt_...",            // unique per event, identical on every retry
  "type": "message.completed",
  "timestamp": "2026-10-05T09:13:20Z",   // when the event happened (UTC)
  "data": { }
}
```

Data per event (fields may be added over time; ignore unknown ones):

- `clone.created` / `clone.updated`: `clone_id`, `status`, `visibility`, and for updates `changed_fields` (names only).
- `conversation.created`: `clone_id`, `conversation_id`, `input_mode`, `started_by` (`owner` or `user`).
- `message.completed`: `clone_id`, `conversation_id`, `message_id`, `role`, `input_mode`, `streamed`, `model`, `latency_ms`, `sources_count`, `memories_used`.
- `voice.completed`: `clone_id`, `conversation_id`, `message_id`, `audio_generated`, `duration_seconds`, `language`.
- `avatar.completed`: `job_id`, `clone_id`, `message_id`, `status`, `duration_seconds`, `provider`, `requested_by`.
- `usage.limit_reached`: `limit`, `used`, `allowed`.
- `subscription.updated`: `subscription_id`, `plan_id`, `status`, `previous_status`.

Respond with any **2xx** status within 10 seconds. Do slow work after responding
(queue it). The response body is ignored.

## Verifying signatures

Your signing secret (`whsec_...`) is shown **once**, when the webhook is created or its
secret is rotated. We don't store it in readable form and can't show it again; rotate
it if it is lost or leaked (the old secret stops being used immediately).

`X-AHC-Signature` is `t=<unix seconds>,v1=<hex>` where

```
v1 = hex(HMAC-SHA256(secret, "<t>." + raw_request_body))
```

To verify:

1. Use the **raw** request body bytes (before any JSON parsing or re-encoding).
2. Recompute the HMAC and compare it to `v1` in constant time.
3. Reject the request if `t` is more than 5 minutes away from your clock (replay protection).
4. Store processed `X-AHC-Event-Id` values and skip ones you've already handled (retries reuse the id).

### Python

```python
import hashlib
import hmac
import time


def verify_signature(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        received = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs(time.time() - timestamp) > tolerance:
        return False  # too old (or from the future): possible replay
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


# Flask example
from flask import Flask, abort, request

app = Flask(__name__)
SECRET = "whsec_..."  # from your secret store, never hard-coded in real code


@app.post("/ahc-webhook")
def ahc_webhook():
    if not verify_signature(SECRET, request.headers.get("X-AHC-Signature", ""), request.get_data()):
        abort(400)
    event = request.get_json()
    # dedupe on event["id"], then queue the work
    return "", 204
```

The backend ships the same helper as `app.developer.webhooks.verify_signature(secret, header, body, tolerance=300)`.

### JavaScript (Node.js)

```js
import crypto from "node:crypto";
import express from "express";

function verifySignature(secret, header, rawBody, toleranceSeconds = 300) {
  const parts = Object.fromEntries((header || "").split(",").map((p) => p.split("=", 2)));
  const timestamp = Number.parseInt(parts.t, 10);
  if (!Number.isFinite(timestamp) || !parts.v1) return false;
  if (Math.abs(Date.now() / 1000 - timestamp) > toleranceSeconds) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.`)
    .update(rawBody)
    .digest("hex");
  const a = Buffer.from(expected, "hex");
  const b = Buffer.from(parts.v1, "hex");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

const app = express();
// Keep the raw body: the signature covers the exact bytes we sent.
app.post("/ahc-webhook", express.raw({ type: "application/json" }), (req, res) => {
  if (!verifySignature(process.env.AHC_WEBHOOK_SECRET, req.get("X-AHC-Signature"), req.body)) {
    return res.sendStatus(400);
  }
  const event = JSON.parse(req.body.toString("utf8"));
  // dedupe on event.id, then queue the work
  res.sendStatus(204);
});
```

## Delivery and retries

- Events are queued and sent by a background worker; they never slow down the action
  that caused them. Expect delivery within a few seconds.
- A delivery succeeds on a 2xx response. Anything else - another status code, a
  timeout (10 s), a connection error, or a redirect (redirects are **not** followed) -
  is retried with exponential backoff: 30 s, 1 min, 2 min, 4 min, ... (capped at
  1 hour), up to `WEBHOOK_MAX_RETRIES` attempts in total (default 5). Then the
  delivery is marked `failed`.
- Every attempt carries the same event id. Events may arrive more than once or out
  of order; use `id` to dedupe and `timestamp` to order.
- The Developer area shows each delivery (status, attempts, last HTTP status, a short
  error) and lets you **retry** a failed delivery (one more attempt, same event id)
  or **send a test event**.
- Turning a webhook off stops new events for it; queued deliveries for it fail with
  "The webhook is turned off."
- Server settings: `WEBHOOK_DELIVERY_ENABLED` (default true; false stops queueing new
  events), `WEBHOOK_MAX_RETRIES` (5), `WEBHOOK_TIMEOUT_SECONDS` (10).

## URL rules (SSRF protection)

Webhook URLs make our server send requests, so they must point to the public internet:

- `https://` only in production (`http://` is accepted only in development, and the
  rules below still apply). No other schemes.
- No `user:password@` credentials and no `#fragment` in the URL.
- No loopback or local targets: `localhost`, `*.localhost`, `127.0.0.0/8`, `::1`, `0.0.0.0`.
- No private networks: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`,
  CGNAT `100.64.0.0/10`.
- No link-local or cloud metadata: `169.254.0.0/16` (including `169.254.169.254`),
  `fe80::/10`, `metadata.google.internal` and similar, `*.internal`, `*.local`.
- No multicast, broadcast, documentation or reserved ranges.
- IPv4 hidden in IPv6 (`::ffff:127.0.0.1`, NAT64, 6to4) is checked as IPv4.
- IP addresses must be written normally: decimal/octal/hex forms such as `2130706433`,
  `0x7f000001`, `0177.0.0.1` or `127.1` are rejected.
- Host names must be fully qualified (`hooks.example.com`, not `redis`).
- Every address the host name resolves to must be public. This is checked when the
  webhook is saved **and again before every delivery**; the request is then sent to
  the address that was checked, so DNS rebinding can't redirect it inside.

## Management API (summary)

All under `/api/developer`, logged-in session. Other users' webhooks return 404.

| Method & path | Result |
| --- | --- |
| `GET /webhooks/events` | `[{event, description}]` |
| `POST /webhooks` `{url, events, organization_id?, is_active?}` | 201, webhook + `secret` (once) |
| `GET /webhooks` | your and your organizations' webhooks |
| `GET /webhooks/{id}` | webhook |
| `PATCH /webhooks/{id}` `{url?, events?, is_active?}` | webhook |
| `DELETE /webhooks/{id}` | 204 |
| `POST /webhooks/{id}/rotate-secret` | webhook + new `secret` (once) |
| `POST /webhooks/{id}/test` | `{delivery_id, status}` |
| `GET /webhooks/{id}/deliveries?page=1&limit=20` | `{items, page, limit, total}` (limit ≤ 100) |
| `POST /webhooks/{id}/deliveries/{delivery_id}/retry` | delivery (failed ones only) |
