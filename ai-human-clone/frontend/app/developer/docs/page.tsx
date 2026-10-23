import Link from "next/link";

import { CodeBlock, CodeTabs } from "@/components/developer/ui";
import { API_URL } from "@/lib/api";

// The API base comes from NEXT_PUBLIC_API_URL (lib/api.ts), never a hard-coded host.
const BASE = `${API_URL.replace(/\/$/, "")}/api/v1`;
const SWAGGER = `${API_URL.replace(/\/$/, "")}/api/v1/docs`;
const OPENAPI = `${API_URL.replace(/\/$/, "")}/api/v1/openapi.json`;

const SECTIONS = [
  ["authentication", "Authentication"],
  ["api-keys", "API keys"],
  ["scopes", "Scopes"],
  ["clones", "Clone API"],
  ["chat", "Chat API"],
  ["search", "Knowledge search"],
  ["voice", "Voice API"],
  ["avatar", "Avatar API"],
  ["analytics", "Analytics API"],
  ["agent", "Agent API"],
  ["webhooks", "Webhooks"],
  ["errors", "Errors"],
  ["rate-limits", "Rate limits"],
  ["examples", "Examples"],
] as const;

const SCOPES: [string, string][] = [
  ["clone:read", "List and read your AI Clones (public profile fields only)."],
  ["clone:chat", "Chat with your AI Clones."],
  ["clone:knowledge:read", "Search knowledge marked public."],
  ["clone:search", "Search all of a clone's knowledge, including private documents."],
  ["conversation:read", "Read API conversations and their messages."],
  ["conversation:write", "Delete conversations."],
  ["voice:transcribe", "Speech to text."],
  ["voice:tts", "Text to speech (and spoken chat answers)."],
  ["avatar:generate", "Create talking-avatar videos."],
  ["analytics:read", "Read clone analytics (counts only, never message content)."],
  ["agent:run", "Start AI agent tasks for a clone (the clone's agent must be turned on)."],
  ["agent:read", "Read the status, steps and result of agent tasks this key can see."],
];

const EVENTS: [string, string][] = [
  ["clone.created", "A clone was created."],
  ["clone.updated", "A clone's settings changed."],
  ["conversation.created", "A new conversation started."],
  ["message.completed", "The clone finished an answer."],
  ["voice.completed", "A voice request finished."],
  ["avatar.completed", "A talking-avatar video is ready (or failed)."],
  ["usage.limit_reached", "A monthly plan limit was reached."],
  ["subscription.updated", "The plan or subscription changed."],
];

function curl(method: string, path: string, body?: string): string {
  const lines = [`curl -X ${method} "${BASE}${path}" \\`, `  -H "Authorization: Bearer $AHC_API_KEY"`];
  if (body) {
    lines[1] += " \\";
    lines.push(`  -H "Content-Type: application/json" \\`, `  -d '${body}'`);
  }
  return lines.join("\n");
}

function js(method: string, path: string, body?: string): string {
  const options = [`  method: "${method}",`, `  headers: {`, `    Authorization: \`Bearer \${process.env.AHC_API_KEY}\`,`];
  if (body) options.push(`    "Content-Type": "application/json",`);
  options.push(`  },`);
  if (body) options.push(`  body: JSON.stringify(${body}),`);
  return [
    `const response = await fetch("${BASE}${path}", {`,
    ...options,
    `});`,
    `if (!response.ok) {`,
    `  const error = await response.json();`,
    `  throw new Error(\`\${error.error}: \${error.message} (request \${error.request_id})\`);`,
    `}`,
    ...(method === "DELETE"
      ? [`console.log(response.status); // 204 No Content`]
      : [`const data = await response.json();`, `console.log(data);`]),
  ].join("\n");
}

function py(method: string, path: string, body?: string): string {
  const call = body
    ? `response = requests.${method.toLowerCase()}(\n    f"{BASE}${path}",\n    headers={"Authorization": f"Bearer {API_KEY}"},\n    json=${body},\n    timeout=60,\n)`
    : `response = requests.${method.toLowerCase()}(\n    f"{BASE}${path}",\n    headers={"Authorization": f"Bearer {API_KEY}"},\n    timeout=60,\n)`;
  return [
    `import os`,
    `import requests`,
    ``,
    `BASE = "${BASE}"`,
    `API_KEY = os.environ["AHC_API_KEY"]`,
    ``,
    call,
    `response.raise_for_status()`,
    method === "DELETE" ? `print(response.status_code)  # 204 No Content` : `print(response.json())`,
  ].join("\n");
}

function examples(method: string, path: string, jsonBody?: string, pyBody?: string) {
  return [
    { label: "curl", code: curl(method, path, jsonBody) },
    { label: "JavaScript", code: js(method, path, jsonBody) },
    { label: "Python", code: py(method, path, pyBody ?? jsonBody) },
  ];
}

const VERIFY_NODE = `import crypto from "node:crypto";

// Use the raw request body (before JSON parsing), e.g. express.raw({ type: "application/json" }).
export function verifyWebhook(rawBody, signatureHeader, secret, toleranceSeconds = 300) {
  const parts = Object.fromEntries(signatureHeader.split(",").map((p) => p.split("=", 2)));
  const timestamp = Number(parts.t);
  if (!timestamp || Math.abs(Date.now() / 1000 - timestamp) > toleranceSeconds) return false;
  const expected = crypto.createHmac("sha256", secret).update(\`\${parts.t}.\${rawBody}\`).digest("hex");
  const given = Buffer.from(parts.v1 ?? "", "hex");
  const wanted = Buffer.from(expected, "hex");
  return given.length === wanted.length && crypto.timingSafeEqual(given, wanted);
}`;

const VERIFY_PY = `import hashlib
import hmac
import time


def verify_webhook(raw_body: bytes, signature_header: str, secret: str, tolerance: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in signature_header.split(","))
    timestamp = parts.get("t", "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > tolerance:
        return False
    signed = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))`;

const ENVELOPE = `POST /your/webhook/url
Content-Type: application/json
X-AHC-Signature: t=1767225600,v1=5f2b…

{
  "id": "evt_…",
  "type": "message.completed",
  "timestamp": "2026-01-01T00:00:00Z",
  "data": { … }
}`;

const ERROR_BODY = `HTTP/1.1 403 Forbidden
X-Request-ID: req_…

{
  "error": "permission_denied",
  "message": "This API key is missing the scope: clone:chat.",
  "request_id": "req_…"
}`;

const RATE_LIMIT_BODY = `HTTP/1.1 429 Too Many Requests
Retry-After: 12
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 12

{
  "error": "rate_limit_exceeded",
  "message": "Too many requests.",
  "request_id": "req_…",
  "retry_after": 12
}`;

const CHAT_LOOP_JS = `// A tiny chatbot: keeps the conversation going with conversation_id.
const BASE = "${BASE}";
const headers = {
  Authorization: \`Bearer \${process.env.AHC_API_KEY}\`,
  "Content-Type": "application/json",
};
let conversationId = null;

async function ask(cloneId, message) {
  const response = await fetch(\`\${BASE}/clones/\${cloneId}/chat\`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (response.status === 429) {
    const wait = Number(response.headers.get("Retry-After") ?? 1);
    await new Promise((r) => setTimeout(r, wait * 1000));
    return ask(cloneId, message);
  }
  if (!response.ok) throw new Error((await response.json()).message);
  const data = await response.json();
  conversationId = data.conversation_id;
  return data.message;
}`;

const CHAT_LOOP_PY = `import os
import time

import requests

BASE = "${BASE}"
session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['AHC_API_KEY']}"


def ask(clone_id: str, message: str, conversation_id: str | None = None) -> dict:
    while True:
        response = session.post(
            f"{BASE}/clones/{clone_id}/chat",
            json={"message": message, "conversation_id": conversation_id},
            timeout=120,
        )
        if response.status_code == 429:
            time.sleep(int(response.headers.get("Retry-After", "1")))
            continue
        response.raise_for_status()
        return response.json()


first = ask("CLONE_ID", "Hi! What do you do?")
follow_up = ask("CLONE_ID", "Which projects are you proudest of?", first["conversation_id"])
print(follow_up["message"])`;

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24 space-y-3">
      <h2 id={`${id}-title`} className="text-xl font-semibold text-white">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Endpoint({ method, path, scope, children }: { method: string; path: string; scope: string; children?: React.ReactNode }) {
  return (
    <li className="rounded-xl border border-border bg-surface-raised/60 p-3">
      <p className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-accent/20 px-1.5 py-0.5 font-mono text-xs text-accent-soft">{method}</span>
        <code className="break-all font-mono text-sm text-white">{path}</code>
        <span className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted">{scope}</span>
      </p>
      {children && <p className="mt-1 text-sm text-muted">{children}</p>}
    </li>
  );
}

const p = "text-sm leading-relaxed text-muted";
const c = "rounded bg-surface px-1 py-0.5 font-mono text-xs text-white";

export default function DeveloperDocsPage() {
  return (
    <div className="lg:flex lg:gap-8">
      <nav aria-label="On this page" className="mb-6 lg:sticky lg:top-24 lg:order-2 lg:mb-0 lg:h-fit lg:w-44 lg:shrink-0">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">On this page</p>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm lg:flex-col">
          {SECTIONS.map(([id, label]) => (
            <li key={id}>
              <a href={`#${id}`} className="inline-flex min-h-10 min-w-10 items-center text-muted hover:text-white lg:min-h-0 lg:min-w-0">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <article className="min-w-0 flex-1 space-y-10">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Developer API</h1>
          <p className={`${p} mt-2`}>
            Use your AI Clones from your own website, app or backend. All endpoints live under{" "}
            <code className={c}>{BASE}</code>. The full reference with every field is in the{" "}
            <a href={SWAGGER} target="_blank" rel="noreferrer" className="text-accent-soft hover:underline">
              interactive API reference (Swagger)
            </a>{" "}
            and the{" "}
            <a href={OPENAPI} target="_blank" rel="noreferrer" className="text-accent-soft hover:underline">
              OpenAPI schema
            </a>
            .
          </p>
        </header>

        <Section id="authentication" title="Authentication">
          <p className={p}>
            Send your API key as a bearer token on every request. API keys are for servers: never put one in browser code,
            a mobile app bundle or a public repository.
          </p>
          <CodeBlock code={`Authorization: Bearer ahc_live_…`} label="Authorization header" />
          <CodeTabs id="auth" examples={examples("GET", "/me")} />
          <p className={p}>
            <code className={c}>GET /me</code> returns the key&apos;s name, owner type, scopes and rate limit — handy to check
            a key works. A missing, wrong, revoked or expired key gets <code className={c}>401</code>.
          </p>
        </Section>

        <Section id="api-keys" title="API keys">
          <p className={p}>
            Create keys on the{" "}
            <Link href="/developer/keys" className="text-accent-soft hover:underline">
              API keys
            </Link>{" "}
            page. The full key is shown only once, right after you create or rotate it — store it in a secret manager or
            environment variable. Afterwards only its prefix (e.g. <code className={c}>ahc_live_Ab3dE6gH</code>) is shown.
          </p>
          <ul className={`${p} list-disc space-y-1 pl-5`}>
            <li>
              <strong className="text-white">Rotate</strong> creates a new secret for the same key; the old one stops at once.
            </li>
            <li>
              <strong className="text-white">Revoke</strong> stops a key permanently. Use it if a key may have leaked.
            </li>
            <li>Keys can expire after 30, 90 or 365 days, or on a date you choose.</li>
            <li>Organization owners and admins can create organization keys, which use the organization&apos;s plan.</li>
          </ul>
        </Section>

        <Section id="scopes" title="Scopes">
          <p className={p}>A key can only do what its scopes allow. Choose the fewest scopes your app needs.</p>
          <div className="overflow-x-auto rounded-2xl border border-border">
            <table className="rtable w-full text-left text-sm md:min-w-[480px]">
              <thead className="bg-surface-raised text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Scope
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Allows
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {SCOPES.map(([scope, text]) => (
                  <tr key={scope}>
                    <td data-label="Scope" className="px-3 py-2 font-mono text-xs text-white">{scope}</td>
                    <td data-label="Allows" className="px-3 py-2 text-muted">{text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section id="clones" title="Clone API">
          <ul className="space-y-2">
            <Endpoint method="GET" path="/clones" scope="clone:read">
              The AI Clones this key can use.
            </Endpoint>
            <Endpoint method="GET" path="/clones/{clone_id}" scope="clone:read">
              One clone&apos;s public profile.
            </Endpoint>
          </ul>
          <CodeTabs id="clones" examples={examples("GET", "/clones")} />
        </Section>

        <Section id="chat" title="Chat API">
          <ul className="space-y-2">
            <Endpoint method="POST" path="/clones/{clone_id}/chat" scope="clone:chat">
              Send a message and get the clone&apos;s answer, grounded in its knowledge. Pass the returned{" "}
              <code className={c}>conversation_id</code> to continue the conversation.
            </Endpoint>
            <Endpoint method="GET" path="/clones/{clone_id}/conversations" scope="conversation:read" />
            <Endpoint method="GET" path="/conversations/{conversation_id}" scope="conversation:read">
              A conversation with its messages.
            </Endpoint>
            <Endpoint method="DELETE" path="/conversations/{conversation_id}" scope="conversation:write" />
          </ul>
          <CodeTabs
            id="chat"
            examples={examples(
              "POST",
              "/clones/CLONE_ID/chat",
              `{"message": "What technologies have you worked with?", "conversation_id": null}`,
              `{"message": "What technologies have you worked with?", "conversation_id": None}`,
            )}
          />
          <p className={p}>
            The response has <code className={c}>conversation_id</code>, <code className={c}>message_id</code>,{" "}
            <code className={c}>message</code> (the answer), <code className={c}>sources</code> (titles and scores, never
            document text) and <code className={c}>created_at</code>. Chat counts toward your plan&apos;s monthly chat
            messages.
          </p>
        </Section>

        <Section id="search" title="Knowledge search">
          <ul className="space-y-2">
            <Endpoint method="POST" path="/clones/{clone_id}/search" scope="clone:search or clone:knowledge:read">
              With <code className={c}>clone:search</code> all knowledge is searched; with{" "}
              <code className={c}>clone:knowledge:read</code> only knowledge marked public. <code className={c}>top_k</code>{" "}
              is 1–20 (default 5).
            </Endpoint>
          </ul>
          <CodeTabs
            id="search"
            examples={examples("POST", "/clones/CLONE_ID/search", `{"query": "Which databases do you use?", "top_k": 5}`)}
          />
        </Section>

        <Section id="voice" title="Voice API">
          <ul className="space-y-2">
            <Endpoint method="POST" path="/clones/{clone_id}/voice/transcribe" scope="voice:transcribe">
              Upload audio (multipart form) and get the text.
            </Endpoint>
            <Endpoint method="POST" path="/clones/{clone_id}/voice/chat" scope="clone:chat + voice:transcribe + voice:tts">
              Speak a question; get the transcript, the answer and a link to the spoken answer.
            </Endpoint>
            <Endpoint method="POST" path="/clones/{clone_id}/voice/tts" scope="voice:tts">
              Turn text (up to 1000 characters) into speech in the clone&apos;s voice.
            </Endpoint>
          </ul>
          <CodeBlock
            label="Transcribe example"
            code={`curl -X POST "${BASE}/clones/CLONE_ID/voice/transcribe" \\\n  -H "Authorization: Bearer $AHC_API_KEY" \\\n  -F "audio=@question.wav"`}
          />
          <CodeTabs id="tts" examples={examples("POST", "/clones/CLONE_ID/voice/tts", `{"text": "Hello, thanks for calling!"}`)} />
          <p className={p}>
            Audio links (<code className={c}>audio_url</code>) are downloaded with the same API key and expire after a while.
            See the{" "}
            <a href={SWAGGER} target="_blank" rel="noreferrer" className="text-accent-soft hover:underline">
              API reference
            </a>{" "}
            for the exact upload fields and supported formats.
          </p>
        </Section>

        <Section id="avatar" title="Avatar API">
          <ul className="space-y-2">
            <Endpoint method="POST" path="/clones/{clone_id}/avatar/video" scope="avatar:generate">
              Start a talking-avatar video. Returns a job; videos take a while.
            </Endpoint>
            <Endpoint method="GET" path="/clones/{clone_id}/avatar/jobs/{job_id}" scope="avatar:generate">
              Poll the job, or subscribe to the <code className={c}>avatar.completed</code> webhook instead of polling.
            </Endpoint>
          </ul>
          <CodeTabs id="avatar" examples={examples("GET", "/clones/CLONE_ID/avatar/jobs/JOB_ID")} />
        </Section>

        <Section id="analytics" title="Analytics API">
          <ul className="space-y-2">
            <Endpoint method="GET" path="/clones/{clone_id}/analytics/overview" scope="analytics:read">
              Totals for a clone (counts only, never message content).
            </Endpoint>
            <Endpoint method="GET" path="/clones/{clone_id}/analytics/activity" scope="analytics:read">
              Activity over time.
            </Endpoint>
          </ul>
          <CodeTabs id="analytics" examples={examples("GET", "/clones/CLONE_ID/analytics/overview")} />
        </Section>

        <Section id="agent" title="Agent API">
          <p className={p}>
            The AI agent works on a goal in a few controlled steps (searching knowledge and memory, calculating, checking the
            date…) and then answers. It only uses the tools the clone&apos;s owner turned on, within the owner&apos;s step and
            time limits. The clone&apos;s agent must be turned on first (Clone › AI Agent); otherwise you get{" "}
            <code className={c}>403</code>.
          </p>
          <ul className="space-y-2">
            <Endpoint method="POST" path="/clones/{clone_id}/agent/run" scope="agent:run">
              Start a task. Body: <code className={c}>goal</code> (1–4000 characters) and an optional{" "}
              <code className={c}>conversation_id</code>. Returns <code className={c}>202</code> with{" "}
              <code className={c}>execution_id</code> and <code className={c}>status</code>.
            </Endpoint>
            <Endpoint method="GET" path="/agent/executions/{execution_id}" scope="agent:read">
              Poll the task: <code className={c}>status</code>, step summaries, <code className={c}>result_summary</code>,{" "}
              <code className={c}>error</code> and <code className={c}>final_message_id</code>.
            </Endpoint>
          </ul>
          <CodeTabs
            id="agent-run"
            examples={examples(
              "POST",
              "/clones/CLONE_ID/agent/run",
              `{"goal": "Summarize my main skills and how many years I have used each.", "conversation_id": null}`,
              `{"goal": "Summarize my main skills and how many years I have used each.", "conversation_id": None}`,
            )}
          />
          <CodeTabs id="agent-status" examples={examples("GET", "/agent/executions/EXECUTION_ID")} />
          <p className={p}>
            Statuses: <code className={c}>queued</code>, <code className={c}>planning</code>,{" "}
            <code className={c}>running</code>, <code className={c}>waiting_confirmation</code>,{" "}
            <code className={c}>completed</code>, <code className={c}>failed</code>, <code className={c}>cancelled</code>{" "}
            and <code className={c}>timeout</code>. Poll every 1–2 seconds until the status is final. Steps contain short
            summaries only — never the model&apos;s private reasoning. A task that needs a person to approve an action stays
            in <code className={c}>waiting_confirmation</code>; approve or reject it in the app. Agent tasks count toward
            your plan&apos;s usage.
          </p>
        </Section>

        <Section id="webhooks" title="Webhooks">
          <p className={p}>
            Add an HTTPS endpoint on the{" "}
            <Link href="/developer/webhooks" className="text-accent-soft hover:underline">
              Webhooks
            </Link>{" "}
            page and choose events. We POST a JSON envelope; reply with any 2xx status within a few seconds. Failed
            deliveries are retried with exponential backoff, and every retry has the same <code className={c}>id</code> so
            you can ignore duplicates.
          </p>
          <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
            {EVENTS.map(([event, text]) => (
              <li key={event} className="text-sm">
                <code className={c}>{event}</code> <span className="text-muted">— {text}</span>
              </li>
            ))}
          </ul>
          <CodeBlock code={ENVELOPE} label="Webhook request" />
          <h3 className="pt-2 text-base font-semibold text-white">Verifying signatures</h3>
          <p className={p}>
            Every request has <code className={c}>X-AHC-Signature: t=&lt;unix time&gt;,v1=&lt;hex&gt;</code>, where{" "}
            <code className={c}>v1</code> is HMAC-SHA256 of <code className={c}>{"`${t}.${raw body}`"}</code> with your
            signing secret. Compare in constant time and reject old timestamps to stop replays.
          </p>
          <CodeTabs
            id="verify"
            examples={[
              { label: "Node.js", code: VERIFY_NODE },
              { label: "Python", code: VERIFY_PY },
            ]}
          />
        </Section>

        <Section id="errors" title="Errors">
          <p className={p}>
            Errors are JSON with <code className={c}>error</code> (a stable code), <code className={c}>message</code> (for
            people) and <code className={c}>request_id</code>. Every response has an <code className={c}>X-Request-ID</code>{" "}
            header — include it when you contact support.
          </p>
          <CodeBlock code={ERROR_BODY} label="Error response" />
          <ul className={`${p} list-disc space-y-1 pl-5`}>
            <li>
              <code className={c}>400</code> invalid input · <code className={c}>401</code> missing or invalid key ·{" "}
              <code className={c}>403</code> missing scope or not allowed · <code className={c}>404</code> not found
            </li>
            <li>
              <code className={c}>429</code> <code className={c}>rate_limit_exceeded</code> or{" "}
              <code className={c}>usage_limit_reached</code> (monthly plan limit) · <code className={c}>5xx</code> a
              problem on our side — retry later
            </li>
          </ul>
        </Section>

        <Section id="rate-limits" title="Rate limits">
          <p className={p}>
            Each key has a per-minute limit that depends on your plan (see{" "}
            <Link href="/developer" className="text-accent-soft hover:underline">
              Overview
            </Link>
            ), plus a monthly request limit. Responses carry <code className={c}>X-RateLimit-Limit</code>,{" "}
            <code className={c}>X-RateLimit-Remaining</code> and <code className={c}>X-RateLimit-Reset</code>. Over the limit you get <code className={c}>429</code> with a{" "}
            <code className={c}>Retry-After</code> header (seconds): wait that long, then retry.
          </p>
          <CodeBlock code={RATE_LIMIT_BODY} label="Rate-limited response" />
        </Section>

        <Section id="examples" title="Examples">
          <p className={p}>A small chatbot that keeps the conversation going and waits on rate limits.</p>
          <CodeTabs
            id="example-chat"
            examples={[
              { label: "JavaScript", code: CHAT_LOOP_JS },
              { label: "Python", code: CHAT_LOOP_PY },
            ]}
          />
          <p className={p}>Delete a conversation (for example when your user asks you to):</p>
          <CodeTabs id="example-delete" examples={examples("DELETE", "/conversations/CONVERSATION_ID")} />
        </Section>
      </article>
    </div>
  );
}
