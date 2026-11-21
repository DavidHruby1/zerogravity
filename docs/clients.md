# Client Operations Guide

Use this page as the operator-facing source of truth for client-specific behavior through ZeroGravity.

## Claude Code

The local deployment accepts Anthropic Messages at `http://127.0.0.1:8741/v1/messages`. Set the base URL to the **origin** and use the proxy's API key. Use the same `ZEROGRAVITY_API_KEY` as Compose. If the key is only in the deployment's `.env`, read it from the running local service into your shell from the repository root.

```sh
ZEROGRAVITY_API_KEY=$(docker compose -f docker-compose.example.yml exec -T zerogravity printenv ZEROGRAVITY_API_KEY)
export ZEROGRAVITY_API_KEY
```

Start Claude Code with the local endpoint.

```sh
export ANTHROPIC_BASE_URL=http://127.0.0.1:8741
export ANTHROPIC_AUTH_TOKEN="${ZEROGRAVITY_API_KEY:?Set the local proxy API key}"
export CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1
export CLAUDE_CODE_MAX_RETRIES=0
claude --model sonnet-4.6
```

With non-streaming fallback disabled, Claude Code 2.1.330 still resent a byte-identical streaming request after a connection closed mid-stream under its default retry settings. Setting `CLAUDE_CODE_MAX_RETRIES=0` stopped that replay in the fixture. This also disables the client's automatic recovery from a transient 503. The binary proxy has its own upstream retry behavior. [Claude Code environment variables](https://code.claude.com/docs/en/env-vars)

Google lists using an Antigravity login with third-party clients, including Claude Code, as grounds for account suspension. [Google FAQ](https://antigravity.google/docs/faq)

### Diagnosing a single-account session

| Observation | What to check |
| --- | --- |
| Healthy process, empty account list or no active account | Check the file bind mount and the account manager before sending generation requests. A short-lived access token can make an initial chat succeed. A successful renewal across an expiry boundary is stronger evidence than a listed account. |
| HTTP 401 | Check the local API key first. For an upstream 401, v1.4.2 documents a reactive access-token refresh. Correlate the upstream response and refresh outcome in local logs. |
| HTTP 403 | Preserve the provider's reason. If it explicitly disables service for this account, stop the operation and all model fallbacks. Other permission errors require their own diagnosis. |
| HTTP 408 or 503 before output | Compare queue depth and wait time with model capacity errors and backend restart logs. Record the time until the first subsequent successful request. |
| Timeout, 504 or disconnect after output begins | Record the last complete event and stop. Replaying can duplicate text or a tool action. |
| A tool fails on the next turn | Check the actual `tool_use` event, its name, structured arguments, and the matching `tool_use_id` in the next user message. A text block containing JSON cannot invoke a tool. |

Run these from the repository root. The status check reads local API state. The stream check sends generation requests and can consume quota.

```sh
python3 scripts/check_proxy.py status
python3 scripts/check_proxy.py stream --model sonnet-4.6
```

After a restart, `python3 scripts/check_proxy.py status --wait-ready 60` measures how long it takes to observe a healthy API and an active managed account. A successful generation or tool check establishes that the language server can handle requests.

Record the image digest, platform, backend version and Claude Code version with the result. For a freeze, correlate client timings with the local queue and backend logs. Count upstream attempts per client operation across retries and model fallbacks. HTTP timings alone cannot reveal the time spent in the queue or the number of upstream attempts.

The opt-in fixture test runs Claude Code against a synthetic API on Docker loopback with external networking disabled and a synthetic key. From the repository root, run `sh tests/claude-code.sh /path/to/claude` with Go, a native Linux Claude Code executable, and a built `zerogravity:v1.4.2-local` image on the same architecture. Pass another local image as the second argument. The test checks two `Read` calls, an explicit 403, an SSE error after text, an interrupted HTTP transfer with and without client retries, and recovery from two 503 responses at the default retry setting.

## OpenCode

- **Supported endpoint style:**
  - Preferred: Gemini v1beta-compatible (`/v1beta/models/{model}:{action}`)
  - Alternative: OpenAI-compatible (`/v1/chat/completions` or `/v1/responses`)
- **Proxy-side transformations that affect UX:**
  - Gemini path is pass-through (least translation overhead).
  - OpenAI path translates messages/tools to Gemini and back.
  - Queue controls serialize requests under contention.
  - Missing max-output fields receive proxy defaults.
- **Recommended defaults:**
  - Use Gemini protocol in OpenCode provider config where possible.
  - Keep declared model limits aligned with real context/output ceilings.
  - Use a single shared base URL per workspace to avoid split routing.
- **Anti-patterns:**
  - Mixing multiple incompatible provider plugins for the same ZeroGravity endpoint.
  - Inflating context/output limits above what models support.
  - Running many parallel subagents without queue tuning.
- **Troubleshooting checklist (429/503/capacity/context):**
  - Verify provider points to `http://localhost:8741/v1beta` (preferred) or `/v1` as intended.
  - Inspect proxy logs for queue timeout vs upstream capacity failures.
  - Reduce parallel jobs/subagents if queue depth or 503s spike.
  - Lower context payload and tool transcript size when context errors appear.

## Generic OpenAI-compatible clients

- **Supported endpoint style:** `/v1/chat/completions` and `/v1/responses`.
- **Proxy-side transformations that affect UX:**
  - OpenAI schema is translated into Gemini-compatible upstream requests.
  - Tool/function declarations are normalized to match Gemini constraints.
  - Missing `max_completion_tokens`/`max_output_tokens` defaults to proxy values.
  - Queue/backoff behavior can surface as wait time, 408 timeout, or 503 overloaded responses.
  - API request size is limited by `ZEROGRAVITY_API_BODY_LIMIT_MB` (default 32 MiB, clamped 1..100).
- **Recommended defaults:**
  - Explicitly set max output tokens and stream when client UX expects incremental output.
  - Keep tool JSON schema conservative and standards-compliant.
  - Configure retry with jittered backoff for 429/503.
- **Anti-patterns:**
  - Assuming OpenAI-specific schema extensions always survive translation.
  - Sending oversized one-shot payloads instead of pruning or chunking context.
  - Unbounded client-side concurrency against a single account.
- **Troubleshooting checklist (429/503/capacity/context):**
  - Confirm base URL points at `/v1` and model name is valid.
  - On 429, inspect quota and account rotation health.
  - On 503, differentiate queue overload vs upstream capacity, then tune queue/concurrency.
  - On context/body failures, reduce message/tool size and verify body limit settings.

## Anthropic-compatible clients

- **Supported endpoint style:** `/v1/messages` (+ `/v1/messages/count_tokens` when used).
- **Proxy-side transformations that affect UX:**
  - Anthropic Messages format is translated to Gemini-backed upstream calls.
  - `budget_tokens` maps to Gemini thinking level tiers for Claude aliases.
  - Missing `max_tokens` is defaulted by the proxy.
  - Queue and upstream cooldown behavior can present as delayed starts or transient 429/503.
- **Recommended defaults:**
  - Keep model IDs on supported aliases and pin known-good defaults in client config.
  - Use bounded `max_tokens` and moderate thinking budgets.
  - Bound retries to transient failures before any stream output.
- **Anti-patterns:**
  - Over-relying on huge `budget_tokens` values for quality gains.
  - Treating every 503 as proxy failure (capacity exhaustion is often upstream).
  - Sending unnecessary full-session transcripts each turn.
- **Troubleshooting checklist (429/503/capacity/context):**
  - Validate `ANTHROPIC_BASE_URL` and authentication header format.
  - Check `/v1/accounts/status` and `/v1/quota` for exhaustion/cooldown clues.
  - For a confirmed transient capacity error before any output, honor the cooldown and use bounded backoff.
  - Trim conversation/tool history when context limits are hit.

