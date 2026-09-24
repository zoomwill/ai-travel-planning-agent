# Phase P14 — Optional Grounded Qwen Reasoning

## What changed after P13

P13 made the existing local workflow observable; it did not add a language model. P14 adds an
optional real Qwen reasoning provider for Planner candidate selection and Reviewer critique. The
default remains the previously verified deterministic implementation so a beginner can run the
project, CI, and every ordinary test without a key, network access, or model cost.

Alibaba Cloud Model Studio is Alibaba Cloud's service for models such as Qwen. Its
OpenAI-compatible endpoint accepts the familiar Chat Completions request shape. This project uses
the official `openai` Python SDK as a protocol-compatible HTTP client, but the remote service and
model are Alibaba Cloud Model Studio and Qwen—not OpenAI models.

## Two explicit modes

- `AGENT_REASONING_MODE=deterministic` creates no Qwen client and uses the P09 local Planner and
  Reviewer.
- `AGENT_REASONING_MODE=qwen` creates one `AsyncOpenAI` client for the FastAPI lifespan and reuses
  it in Planner and Reviewer.

The API key comes only from `QWEN_API_KEY` or `DASHSCOPE_API_KEY` as a Pydantic `SecretStr`. It is
never placed in LangGraph State, checkpoints, preference Store, SSE, metrics, Grafana, responses,
logs, or documentation. `GET /api/v1/llm/status` reads cached safe diagnostics and makes no paid
call.

`QWEN_MODEL` accepts only a bounded Qwen model identifier. Whitespace, control text, non-Qwen
names, and credential-shaped values are rejected before that field can appear in status or logs.

## Region and base URL safety

A Model Studio key must be used with its matching region. Before constructing the SDK client, the
application requires HTTPS, the exact `/compatible-mode/v1` path, no credentials/query/fragment,
and one current official host:

- `dashscope.aliyuncs.com` (China/Beijing)
- `dashscope-intl.aliyuncs.com` (Singapore)
- `dashscope-us.aliyuncs.com` (United States)
- `cn-hongkong.dashscope.aliyuncs.com` (Hong Kong)
- a single workspace/trial label on a documented regional `*.maas.aliyuncs.com` host

This allowlist prevents a typo or malicious setting from sending the API key to localhost, an IP,
`example.com`, or another server. There is deliberately no insecure development override.

## Provider architecture and lifecycle

Graph code depends on the business-specific `StructuredLLMProvider` protocol, not the SDK. It has
separate `plan()`, `review()`, and explicit `smoke_test()` operations rather than one unbounded
"do anything" method. `QwenStructuredLLMProvider` owns real JSON requests. The deterministic
`FakeStructuredLLMProvider` owns no network client and supplies unit tests and offline graph runs.

One provider/client is built during FastAPI startup, injected into both the direct and persistent
compiled graphs, and closed during lifespan cleanup. SDK response objects, exceptions, generators,
and clients never enter graph State, PostgreSQL checkpoints, or the preference Store. Strict
MessagePack therefore continues to serialize only validated domain/JSON-safe data.

## Structured JSON, not guessed text

Planner and Reviewer calls use:

```python
response_format = {"type": "json_object"}
extra_body = {"enable_thinking": False}
max_completion_tokens = 2048
```

Their prompts explicitly request JSON. The response content passes through a strict `json.loads()`
configuration and a dedicated strict Pydantic model. Duplicate object keys, non-standard `NaN` or
infinity values, numeric strings where JSON numbers are required, unknown fields, invalid enums,
excessive lengths, malformed JSON, and out-of-range scores fail with stable safe codes. There is no
regular-expression JSON extraction, `eval`, YAML, or natural-language guess. Hidden reasoning is
neither requested nor saved. Low temperature and non-thinking mode target stable structured
decisions; real LLM wording is still not guaranteed deterministic.

## Planner grounding and candidate IDs

Qwen does not write a free-form `TravelPlan`. Before the Planner call, application code builds a
bounded DTO containing only trip requirements, current/remembered preferences, at most four
bounded RAG contexts, revision controls, and validated candidate summaries. Every existing
flight, hotel, and attraction gets a stable key:

```text
kind + "_" + first 24 hexadecimal characters of
SHA-256(canonical validated domain-model JSON)
```

Provider data itself is unchanged. `QwenPlanDecision` may return only one flight ID, one hotel ID,
an ordered list of attraction IDs for every requested day, and bounded notes. It has no price,
airline, hotel-fact, weather, or route field. Application code rejects unknown IDs, duplicate
attractions, missing/reordered days, too many daily activities, and choices that bypass an active
lower-cost revision policy. It never guesses a "nearby" ID.

After validation, the existing planning service receives the exact original domain objects. It
calculates itinerary dates and total cost deterministically from provider prices. Thus Qwen can
choose and arrange known candidates, but cannot invent or alter travel facts.

Post-P19 maintenance: prompt and validation share the same invocation-local registry, bounded
to the first 20 flights, 20 hotels and 40 attractions, then deduplicated by stable ID. Candidate
IDs are exact opaque strings: no trimming or case normalization. An otherwise schema-valid
decision with an unknown flight, hotel or daily attraction ID gets **one** semantic repair call.
The prompt repeats the same safe candidate context/allowlist with a fixed repair instruction;
it does not include the rejected completion. The second decision must pass every grounding rule.
Duplicate attractions, day-sequence errors and revision-policy violations alone do not get repair.
An unsuccessful repair ends with `llm_grounding_violation`, even when deterministic fallback was
configured; intake remains retryable and no invented plan is saved. This does not re-execute
the graph, five searches or Reviewer. Each genuine Reviewer-driven Planner revision gets its own
one-repair budget, without changing the maximum review rounds.

JSON Object mode is retained: the existing adapter/model configuration does not establish
support for runtime schema enums. [Current Alibaba documentation](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)
limits JSON Schema mode to selected model families; an offline mock cannot prove cloud support.
Application-side strict JSON, schema and grounding validation remains authoritative.

## Reviewer and bounded reflection

`QwenPlanReview` supplies four bounded dimension assessments, critique, allowlisted issue codes,
and bounded suggested text. It has no decision field. The application averages the four dimensions,
compares the configured threshold, counts the round, and enforces `REVIEW_MAX_ROUNDS`. On the last
low-scoring round it forces finalization exactly as P09 did.

Only validated `ReviewIssueCode` values reach the existing `RevisionPolicy`. Suggested natural
language is never executed, cannot call tools, and cannot become Python code. The checkpoint stores
the existing sanitized `PlanReview`, not raw model output.

## Prompt-injection boundary

User preferences, provider descriptions, and RAG text are untrusted data. They are length-bounded;
common credential assignments, bearer values, key shapes, and DSNs are redacted. Literal angle
brackets are JSON-escaped before the data is placed inside explicit `<UNTRUSTED_DATA>` delimiters,
so injected closing-tag text cannot terminate the block. The system message says that instructions
inside those blocks cannot override the rules, request tools, or reveal secrets. This prompt
boundary reduces instruction-following risk; the decisive protection is still application-side
schema and candidate-ID validation.

No DSN, API key, internal configuration, log, full graph State, full checkpoint history, MCP
client, or unrelated preference namespace is sent to Qwen.

## Retries, timeout, and fallback

`QWEN_TIMEOUT_SECONDS` defaults to 30 seconds. The SDK's built-in retries are disabled, and the
project performs at most `QWEN_MAX_RETRIES` (default one, allowed zero to two) for timeout, rate
limit, transient connection, and server failures. Authentication, invalid URL, malformed JSON,
schema failure, and grounding failure are not retried indefinitely. Retry waits are short and
bounded. `QWEN_MAX_COMPLETION_TOKENS` defaults to 2048 and is limited to 256–4096. It is passed as
Model Studio's current `max_completion_tokens` parameter, so one attempt cannot request the
model's full maximum output length.

Semantic repair is separate from `QWEN_MAX_RETRIES`; no new retry setting is added. Per Planner
invocation there are at most two semantic calls and at most `2 * (QWEN_MAX_RETRIES + 1)` HTTP
attempts (four at the default, six at the configured maximum). These are ceilings, not claimed
usage; both transport attempts and timeouts can incur provider cost. Cancellation propagates
through a pending repair and SSE disconnect cleanup cancels/awaits the producer. The existing
client lifespan and request timeout are unchanged.

`travel_planner_planner_grounding_total{outcome="valid|repaired|failed"}` records bounded semantic
outcomes, once per completed grounding invocation. It has no ID, location, user, token or prompt
labels. Parsing/transport failure before grounding remains in existing LLM request metrics;
cancellation is not mislabeled as a grounding failure.

Deterministic fallback defaults to false. When explicitly true, every Planner and Reviewer use of
the deterministic path is recorded in both safe logs and `status="fallback"` metrics, including a
Qwen-mode startup with no configured provider. It is never presented as Qwen success. P14
acceptance uses fallback disabled.

Stable public failure codes are `llm_not_configured`, `llm_invalid_base_url`, `llm_timeout`,
`llm_rate_limited`, `llm_authentication_failed`, `llm_transport_error`, `llm_invalid_json`,
`llm_schema_validation_failed`, `llm_grounding_violation`, and `llm_provider_error`. SDK exception
text and tracebacks are not returned.

## Existing phases remain in control

- P08 still launches five independent LangGraph `Send` search workers before Planner; Qwen does
  not serialize flight, hotel, attraction, weather, and route calls.
- P09 still owns revision actions, threshold, maximum rounds, and recursion protection.
- P10 keeps deterministic multi-query expansion. P14 deliberately does not add the optional Qwen
  query expander, so an extra paid/unstable call cannot affect retrieval.
- P11 keeps the fixed `SearchKind → MCP tool` mapping. Qwen cannot choose or call MCP tools.
- P12 still executes the graph exactly once and streams workflow progress. It is not model token
  streaming.
- P13 gains low-cardinality LLM request, duration, and provider-reported token metrics plus four
  dashboard panels. Prompt, user, thread, response, and error text never become labels.

Token counters increment only when the real SDK response contains usage. Missing usage is not
estimated. Logs may contain role, configured model, duration, status, and real token counts; they
never contain prompt, completion, full plan, RAG context, user request, or chain of thought.

## Enable, verify, and disable

Copy only variable names from `.env.example` into the ignored `.env`, choose the endpoint for your
key's region, and set:

```dotenv
AGENT_REASONING_MODE=qwen
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=replace-with-your-own-key
QWEN_MAX_COMPLETION_TOKENS=2048
QWEN_ALLOW_DETERMINISTIC_FALLBACK=false
```

Run one deliberately paid short request:

```bash
uv run python scripts/check_qwen.py
```

It prints PASS/FAIL, the returned model identifier, and real token usage only when supplied. It
does not print the key or a full SDK exception. A missing key produces a nonzero exit code.

Run the ordinary offline suite without any Qwen call:

```bash
uv run pytest tests/llm -q
uv run pytest -q
```

The separately enabled Docker integration suite also pins its in-process applications to
deterministic mode. Therefore `RUN_INTEGRATION_TESTS=1` alone cannot inherit a local qwen-mode
`.env` and create paid calls. Only `RUN_LLM_INTEGRATION_TESTS=1` enables the real Qwen invariant
test.

The one real invariant test is separately gated and can incur cost:

```bash
RUN_LLM_INTEGRATION_TESTS=1 uv run pytest -m llm_integration -q
```

Disable Qwen by restoring `AGENT_REASONING_MODE=deterministic`; no key is required. P14 is complete
when offline checks pass, qwen mode can produce a grounded validated plan with an available real
key, no secret appears in repository/logs/state/metrics, and deterministic mode still passes all
P00–P13 tests.

## Current limitations

Flights, hotels, attractions, weather, routes, and MCP outputs remain deterministic mock data.
There is no live inventory, booking, payment, frontend, authentication, production TLS, or public
deployment. The RAG corpus is a local demo. Qwen reasons over supplied fixtures and is not a source
of current travel facts. SSE reports agent workflow progress rather than token-level model output.

## Official references used for P14

- Alibaba Cloud Model Studio base URLs and regions:
  <https://www.alibabacloud.com/help/en/model-studio/base-url>
- Alibaba Cloud Model Studio structured output:
  <https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output>
- Alibaba Cloud Model Studio OpenAI-compatible Chat parameters:
  <https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions>
- Alibaba Cloud Model Studio error codes:
  <https://www.alibabacloud.com/help/en/model-studio/error-code>
- Official OpenAI-compatible Python SDK repository:
  <https://github.com/openai/openai-python>
