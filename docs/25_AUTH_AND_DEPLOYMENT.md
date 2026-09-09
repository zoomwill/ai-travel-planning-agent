# P18 — Authentication and deployment

P17 is committed as `aa5d8aa`. The clean P18 baseline after an authorized fast-forward is
`31007f8`. P18 adds authenticated identity and deployable artifacts without changing travel
facts, booking scope, the five search branches or the planning/review graph.

Real Auth0 login, GitHub-hosted CI, Railway and Vercel deployment are **NOT VERIFIED** until
their actual account-side acceptance is performed. Local tests do not prove cloud deployment.
See `P18_ACCEPTANCE_REPORT.md` for executed results and remaining limitations.

## 1. Authentication versus authorization

Authentication asks “who signed in?” Authorization asks “which user's data may this request use?”
The old random browser UUID answers neither question. `AUTH_MODE=demo` preserves that local
workflow. `AUTH_MODE=auth0` requires a verified access token at the FastAPI boundary.

Auth0 Universal Login handles passwords and login UI. The React SDK uses OAuth Authorization
Code Flow with PKCE: a per-login proof binds the browser's code exchange. OIDC adds identity
information. This application does not implement passwords, password reset, MFA or cookie sessions.
The SPA has a public client ID, not a client secret. [Auth0 React SDK](https://auth0.com/docs/libraries/auth0-react).

The API accepts **API access tokens**, not profile ID tokens. PyJWT verifies RS256, exact issuer,
the configured API audience, expiry and required nonempty subject; `nbf`/`iat` are checked when
present. RSA keys come only from the configured issuer's `/.well-known/jwks.json`, never token
`jku`, `x5u` or a client-provided URL. HS256/none are not configurable alternatives.
[PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html).

JWKS uses one lifespan-owned async HTTP pool, HTTPS DNS origin validation, no redirects or
environment proxy inheritance, a 64 KiB response bound and at most 32 keys. Cache TTL defaults
to one hour; reads have both socket and total deadlines. Unknown `kid` triggers at most one
forced refresh, with a shared 30-second cooldown against random-kid floods. Cold-cache misses
perform one fetch. Rotation inside the cooldown may temporarily fail closed. Cache fetch failure
also has a 30-second cooldown. Cancellation propagates; there is no authentication retry loop.

## 2. Identity and thread isolation

`CurrentPrincipal` contains only the verified subject and a stable internal reference. The
reference is SHA-256 over a domain separator, normalized issuer and subject with unambiguous
separators. This is **pseudonymization, not encryption**. Raw subject is excluded from repr and
is not copied into graph state, preferences, logs or metrics. Profile name remains browser-only.

In Auth0 mode all legacy `user_id` body/query/path values are ignored for ownership. They may
still be supplied for compatibility, but cannot change the principal. New request bodies may
omit `user_id`. Demo mode still requires a valid local user identifier.

Public thread IDs retain the existing 1–128-character alphanumeric/dot/underscore/hyphen
validation; the frontend generates UUIDs. PostgreSQL checkpoint keys in Auth0 mode are
`auth0:<user_ref>:<public_thread_id>`. User A and User B may use the same public UUID without
sharing a checkpoint. Conversation Store and preference Store also use the verified user scope.
Existing demo checkpoints are not automatically imported into authenticated accounts.

Use `GET /api/v1/me/preferences` and `DELETE /api/v1/me/preferences/{preference_id}` in Auth0
mode. Legacy `/users/{user_id}/preferences` routes also operate only on the principal's own
namespace, regardless of path ID. Missing resources return 404, not another user's data.
Preference responses project internal source checkpoint keys back to public thread IDs.

## 3. HTTP boundaries

| Route group | Auth0 policy |
|---|---|
| Conversation messages/read/reset/confirm/confirm-stream | Token required; verified user namespace |
| Persistent plans, plan streams, state and history | Token required; scoped checkpoint key |
| Direct Agent plan and deterministic mock plan | Token required; planning admission applied |
| Preferences, including legacy routes | Token required; own namespace only |
| RAG search/status, MCP status, LLM status, travel-data status | Token required |
| `/health`, `/ready`, `/health/ready` | Public, safe liveness/dependency summaries |
| `/metrics` | Local toggle; disabled in production (404) |
| `/docs`, `/redoc`, `/openapi.json` | Local toggle; disabled in production (404) |

Production requires exact HTTPS CORS origins, explicit API trusted hosts, and disabled public
docs/metrics. CORS accepts Authorization, Content-Type and X-Request-ID; exposes X-Request-ID
and Retry-After. It does not enable cookie credentials or wildcard origins. Conservative
nosniff/referrer/permissions headers are added without buffering SSE. No untested CSP is added.

## 4. Cost protection

Redis Lua atomically checks all relevant fixed-window buckets, then increments them together.
If any cap is exhausted, none is incremented. UTC minute/day boundaries determine expiry.
Keys use pseudonymous references and a separate `rate:{travel-auth}:` namespace, not RAG keys.
The hash tag also keeps each script's keys in one Redis Cluster slot.

| Setting | Default | Allowed range |
|---|---|---|
| AUTH_RATE_INTAKE_PER_MINUTE | 10 | 1–100 |
| AUTH_RATE_INTAKE_PER_DAY | 50 | 1–1000 |
| AUTH_RATE_GLOBAL_INTAKE_PER_DAY | 200 | 1–5000 |
| AUTH_RATE_PLAN_PER_DAY | 3 | 1–100 |
| AUTH_RATE_GLOBAL_PLAN_PER_DAY | 20 | 1–1000 |

All protected POST operations except reset consume planning capacity; messages use intake
capacity. This conservatively includes direct mock plans and RAG search. Admission occurs once
before endpoint execution/SSE preparation; invalid or failed attempts can consume a slot and
are not refunded. No automatic mutation retry is added. Fixed windows can admit up to two
windows' allowance across a boundary; these are request caps, not a currency/billing guarantee.
Existing bounded model/provider retry and review limits remain separate.

429 returns a fixed safe code/message and Retry-After, not remaining global capacity or
another user's usage. Redis failure returns 503 and prevents expensive work in Auth0 mode.
There is no production rate-limit off switch. Demo mode bypasses auth admission for local use.
An additional global intake cap closes the multi-account intake-only model-cost gap.

`travel_planner_auth_events_total` uses bounded operation/outcome categories only.
Missing/inaccessible checkpoint or preference resources count as authorization denied without
probing another owner's namespace. JWTs,
subject, email, IP, user/thread IDs and key IDs are never metric labels. No token or claim
logging is introduced. This protection is not a substitute for an operator's cloud spending
limits, abuse monitoring or edge denial-of-service controls.

## 5. Frontend sessions and SSE

`VITE_AUTH_MODE=demo` keeps local development account-free. In `auth0` mode the Auth0 provider
shows loading/sign-in/error states before mounting the workspace. SDK tokens use in-memory
cache; application code never puts them in localStorage, sessionStorage or IndexedDB.

The SDK's access-token getter is injected through React context, not a global mutable token.
The central client adds Bearer authorization to protected JSON and POST fetch/ReadableStream
requests. It checks cancellation after token acquisition. 401 says to sign in again, 403 explains
access denial, and 429 explains daily capacity. None causes a message or confirmation replay.
The existing GET/state resynchronization remains available after authentication; SSE business
events, comment keepalive, sequence validation and terminal rules remain unchanged.

Account-specific local thread pointers use a deterministic browser hash namespace. Auth0 mode
does not create/use the demo localStorage user ID as identity. Logout unmounts the workspace,
cancels its operations, clears that session's local thread metadata and calls SDK logout.
It does not delete backend conversations or preferences. Logout deliberately discards the local
recent-thread list; full server-side thread discovery is not implemented in this phase.

## 6. Container and RAG strategy

`Dockerfile` uses verified immutable Python 3.12/uv image digests and `uv sync --locked --no-dev`.
Linux selects official CPU Torch 2.13.0; macOS retains its existing package source. The first
Linux build exposed unnecessary CUDA dependencies, which were removed by this source selection.
[uv PyTorch integration](https://docs.astral.sh/uv/guides/integration/pytorch/).

The measured pre-existing host model cache was approximately 458 MB. The image explicitly
prepares the same `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model at revision
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42` during build. Runtime is offline for model loading;
there is no download per request or model substitution. Build networking/model download is
required on a cold build. Final measured image size, if verified, is in the acceptance report.

Only application code, locked dependencies, README and required knowledge corpus are copied.
`.dockerignore` excludes real env files, Git metadata, caches, generated data, tests, docs and
frontend artifacts. No runtime secrets are build arguments. Runtime UID/GID is 10001.
The image defaults to production/Auth0 with docs/metrics disabled; missing safe configuration
prevents startup. The local container checker explicitly selects development/demo instead.

`python -m app.deployment.start` is the single entry point. It validates configuration, runs
bootstrap before traffic, then starts one Uvicorn worker on `0.0.0.0:$PORT`, without duplicate
access logs. Uvicorn handles normal SIGTERM/lifespan shutdown; startup failures use fixed safe
messages. Proxy headers are not trusted for identity or host decisions.

Bootstrap serializes overlapping deployments with a PostgreSQL advisory lock, invokes official
LangGraph saver/store setup, loads prepared weights, and adds missing P10 child IDs. It restores
Redis parent documents and deterministic local manifests. It never resets Chroma, flushes Redis,
or deletes old index IDs; incompatible existing IDs/counts fail for manual migration review.
It preserves `travel_knowledge_children_v1`. Repeated startup safely reuses matching indexes.

The local manifest is reproducible metadata rebuilt per API container, not user persistence.
User checkpoints/preferences live in PostgreSQL; vectors in persistent Chroma; caches and quotas
in Redis. Production startup also refuses an unavailable RAG runtime.

## 7. Manual Auth0 setup (no secrets in chat or the SPA)

1. In your own Auth0 account, create a **Single Page Application** for the frontend.
2. Create a separate Auth0 **API**, select **RS256**, and choose a stable API Identifier/audience.
   The audience is not the SPA client ID. Do not use an Auth0 Management API audience.
3. Set all three dashboard fields: Allowed Callback URLs, Allowed Logout URLs, Allowed Web Origins.
4. For local testing use the exact origins `http://127.0.0.1:5173` and `http://localhost:5173`.
5. Add the exact Vercel production origin to each field when known. Do not use wildcard callbacks.
6. Set frontend public domain, client ID and audience. Set backend issuer (HTTPS, normalized slash)
   and the same API audience. No Auth0 client secret is needed by this SPA/API design.
7. Perform one local redirect login, conversation, reload and logout; confirm a logged-out
   protected request returns 401. Do not copy tokens into commands, logs or screenshots.
8. If two test accounts are available, use the same public thread UUID and verify mutual
   isolation of draft, state, history and preferences. Otherwise real two-user acceptance remains
   NOT VERIFIED; offline cryptographic two-user tests are mandatory and separate.

SDK silent renewal can be affected by browser cookie restrictions. A visible sign-in-again path
is retained instead of silently replaying mutations. Real browser compatibility requires the
above account-side acceptance, not just mocked SDK tests.

## 8. Manual Railway setup and private services

Creating/activating cloud services can incur charges. The **user** must choose the plan and
provision resources; no account, upgrade, domain or credits are purchased automatically.

1. Create a Railway project/environment and private PostgreSQL/Redis services. Review billing first.
2. Create a separate Chroma image service using the existing `chromadb/chroma:1.5.9` image.
   Attach its volume at `/data`, matching local Compose, and keep internal port 8000. Do not add
   a public Chroma domain or TCP proxy. Do not copy the whole local Compose stack into one service.
3. PostgreSQL/Redis also need their service persistence and private networking. Remove unnecessary
   public TCP proxies; application variables should reference private service hosts.
4. Create only the FastAPI service from the repository root with `Dockerfile` and `railway.toml`.
   Add a public HTTPS API domain; keep one replica. Do not override the Python start command.
5. Fill the settings below using Railway variable references/private values in its dashboard.
   API service needs no filesystem volume: its model is baked in and local manifests are rebuilt.
6. Use `/ready` for activation, with the checked-in 600-second timeout. Include
   `healthcheck.railway.app` in trusted hosts alongside the actual API hostname.
7. Enable GitHub integration **Wait for CI** after the workflow is pushed and observed passing.
   No Railway token is required inside ordinary GitHub Actions jobs.

Railway volumes become available at runtime, not build or pre-deploy time. Therefore bootstrap
runs in the service start command. Chroma volume ownership must be checked with the pinned image;
do not weaken the non-root API container to solve a different service's volume permissions.
[Railway volumes](https://docs.railway.com/volumes),
[healthchecks](https://docs.railway.com/deployments/healthchecks),
[Wait for CI](https://docs.railway.com/deployments/github-autodeploys).

| Backend variable | Railway value/policy |
|---|---|
| APP_ENV / AUTH_MODE | production / auth0 |
| AUTH0_ISSUER / AUTH0_AUDIENCE | Your issuer and API audience |
| CORS_ALLOWED_ORIGINS | JSON list containing only the exact HTTPS frontend origin |
| TRUSTED_HOSTS | JSON list of actual API host and healthcheck.railway.app |
| API_DOCS_ENABLED / METRICS_ENABLED | false / false |
| POSTGRES_HOST / PORT / USER / PASSWORD / DB | Map private PostgreSQL service variables to corresponding POSTGRES_* names |
| REDIS_HOST / PORT / PASSWORD | Private Redis host/port/password; optional ACL REDIS_USERNAME |
| REDIS_SSL | Match your private Redis service's TLS support, do not guess |
| CHROMA_HOST / PORT / SSL | Private Chroma hostname / 8000 / false on private HTTP networking |
| TRAVEL_SEARCH_BACKEND_MODE | direct; cloud MCP topology is intentionally rejected in P18 |
| AGENT_REASONING_MODE | deterministic initially; qwen only after cost controls/account configuration |
| QWEN_API_KEY | Backend-only service secret when Qwen is selected |
| TRAVEL_DATA_MODE | demo initially; external only after selected credentials and caps are configured |
| DUFFEL_ACCESS_TOKEN / LITEAPI_API_KEY | Backend-only secrets; keep test/sandbox environments for this demo |

Use reference variables rather than hardcoding DSNs into application code. Never paste secret
values into README, GitHub workflow, Docker build arguments, frontend env or this conversation.
Public diagnostics require authentication; public metrics and OpenAPI remain disabled.

## 9. Manual Vercel setup

1. Import the existing repository only when you choose to deploy; set Root Directory `frontend`.
2. Use Vite, `npm ci`, `npm run build`, output `dist`, Node 24 and the checked-in `vercel.json`.
3. Set only public values: VITE_AUTH_MODE=auth0, VITE_AUTH0_DOMAIN, VITE_AUTH0_CLIENT_ID,
   VITE_AUTH0_AUDIENCE, VITE_API_BASE_URL (the HTTPS Railway API origin).
4. The Vercel production build rejects demo auth, missing Auth0 values or a non-HTTPS API origin.
5. Add the resulting exact production origin to Railway CORS and all three Auth0 URL fields.
6. Verify the SPA rewrite, security headers, redirect return and authenticated POST SSE over HTTPS.
   There are no Vercel serverless API functions; FastAPI remains the backend.

Local development uses relative API paths through the Vite proxy. The deployed frontend calls
Railway directly; it does not rely on a Vercel proxy to buffer SSE.
[Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite).

## 10. CI and local verification commands

The workflow triggers on pull requests and pushes to main, with contents:read only. Official
checkout/setup actions are pinned to observed SHAs. Backend uses Python 3.12/uv; frontend Node 24.
No provider/Auth0 secrets are provided. Ordinary tests use local RSA and fake transports, and
real HTTP transports to providers/JWKS are blocked unless explicitly gated.

From the project root, these commands install locked dependencies and check style, types and
offline behavior. Success means zero exit codes; a failing assertion is not a cloud failure.

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest tests/auth tests/deployment -q
uv run pytest -q
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

The last command requires Docker Desktop/core services. It validates local infrastructure and
Redis Lua, not Auth0/Qwen/travel providers. From `frontend`, run:

```bash
npm ci
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run test:e2e
```

For explicit local container acceptance, first start Docker Desktop and existing core services:

```bash
docker compose up -d --wait
docker build -t travel-planner:p18 .
uv run python scripts/check_deployment.py
```

The checker uses only the existing local Compose network and database settings, an ephemeral
localhost port, demo providers, deterministic reasoning and no mounted API volume. It checks
health/readiness/RAG/planning/restart/shutdown, then removes only its own temporary container.
Passwords are passed by inherited environment-variable name, not printed or written to a file.
Docker credential-helper hangs are a separate local CLI issue; do not expose credentials to debug.

## 11. Real cloud acceptance checklist — still required

- Actual GitHub Actions run succeeds after a separately authorized push.
- HTTPS frontend loads; backend /health and /ready succeed; plain logged-out protected API is 401.
- Auth0 login returns to Vercel and API accepts its access token; invalid/ID tokens are rejected.
- One quota-approved small authenticated conversation/confirmation completes via POST SSE;
  Authorization, exact CORS, comment keepalive and terminal event work over public networking.
- Same user/thread survives an API restart/redeploy. Chroma collection/count survives a separate
  Chroma restart without deleting its volume. Confirm private Postgres/Redis/Chroma endpoints.
- Two-account real isolation if available; otherwise explicitly NOT VERIFIED.
- Audit service variables and image/bundle without printing secret values. Do not infer cloud
  variable safety from local repository scanning alone.

Until these are run, use “P18 implementation ready; cloud/auth configuration pending,” not
“P18 complete.” Hosted test/sandbox data is still not live or bookable inventory. Duffel Stays
remains optional/unverified, with no booking or payment functionality.

## 12. Rollback and shutdown

Disable autodeploy before investigating a failing deployment. Use the platform's prior known-good
deployment, not a Git reset/rebase or destructive database migration. Never roll a public API back
to unauthenticated P17 while exposing its domain. Keep auth/caps enforced or take the API offline.
Preserve PostgreSQL, Redis and Chroma volumes; do not flush quotas or indexes to “fix” deployment.
Suspend/delete cloud compute only through an explicit user decision after checking data retention
and billing. Locally, `docker compose stop` retains containers/data; `docker compose down` retains
named volumes. Do not run `docker compose down -v` during this phase.

Remaining architecture limits include one worker/replica, no distributed same-thread mutation
lock, conservative fixed-window quotas, no full server-side thread discovery, no public Grafana,
no cloud MCP deployment and no new token replay/streaming capabilities. No P19 work is included.

## 13. Railway first-index bootstrap troubleshooting

The focused follow-up to committed P18 (`b249bb5`) preserves `/ready`, the private services and
all P10 content/model/retrieval choices. Set `RAG_BOOTSTRAP_BATCH_SIZE=8` (default; integer 1–32)
on the API service. This controls deployment document writes **and** their model encode batches;
normal runtime query/indexing defaults are not changed. A fresh 77-child corpus takes ten
sequential batches: nine of eight and a final five. Existing IDs are skipped in stable corpus order.

The old adapter accepted all missing children in one call. Sentence Transformers still had its
own default internal batch size of 32; it was not necessarily computing all 77 simultaneously.
Both `encode_document` and the `encode` fallback support an explicit `batch_size`.
[Official encoding API](https://sbert.net/docs/package_reference/sentence_transformer/model.html).

Flushed `BOOTSTRAP stage=...` lines now identify PostgreSQL, model load, corpus, Chroma connection,
existing IDs, every batch start/complete, final count, Redis, manifest, memory release and completion.
They contain only fixed stage names and bounded integer counts. For a normal Python exception,
the entry point prints only phase and class, for example:

```text
FAIL deployment startup phase=bootstrap error_type=ConnectError
```

No exception text, traceback, DSN, credentials or chunk text is printed. The last stage helps
locate the failed operation. SIGKILL/OOM cannot reliably execute Python cleanup or print a final
failure line; absence of that line alone does **not** prove OOM. Check platform exit/OOM events
alongside the stage timeline. Repeated weights progress may span container restarts; it does not
prove eleven simultaneously live models in one process.

Bootstrap owns the temporary model/vector/corpus in an inner coroutine, then performs one cyclic
GC pass after that coroutine has returned. Only afterwards may `create_app` and lifespan load
the normal runtime model. Tests include cyclic weak references and the actual runtime factory
boundary. This proves reference release in the test, not that native allocators immediately
return all resident pages to the OS. No private PyTorch API or per-request GC is used.

Railway private networking is scoped to a project/environment and uses a private mesh; services
do not need public domains for cross-region communication. Region separation can increase
round-trip time, particularly across multiple sequential batches, but is not evidence of the
reported crash. Keep PostgreSQL, Redis and Chroma private; do not replace `/ready` with `/health`.
[Railway private networking](https://docs.railway.com/networking/private-networking/how-it-works).

### Local first-start reproduction

Start Docker Desktop and the existing core services. The build command prepares the unchanged
model in the image. The checker creates an **isolated private test Chroma** with temporary tmpfs
data, keeps the normal collection name, and caps its temporary API container at 1 GiB with no
additional swap. It does not clear the existing Chroma collection or delete any named volume.

```bash
docker build -t travel-planner:p18 .
uv run python scripts/check_deployment.py --fresh-index
```

**Observed limitation:** the local 1 GiB/no-extra-swap test was OOM-killed (137) during
`embedding_load_start`, before any indexing batch. Batching cannot remove that model-load
working-set requirement. The existing Railway 1 GB setting has not been changed and is not
claimed fixed. For a separate **local-only** capacity comparison, explicitly run:

```bash
uv run python scripts/check_deployment.py --fresh-index --memory-mib 2048
```

This does not provision or resize Railway. Review actual platform OOM events and billing before
choosing any cloud resource change. A local 2 GiB result is not a production capacity guarantee.
The installed Transformers version discards the old `low_cpu_mem_usage` argument; adding that
flag would not be an effective fix. Precision, quantization and model choice are not changed.

Success requires all 77 children, exactly ten batches, bootstrap completion, a served `/ready`
200, a deterministic plan, repeated readiness checks, an idempotent restart and graceful shutdown.
Only the test containers/tmpfs are removed afterwards. If Linux cgroup v2 `memory.peak` is
available, the script reports its observed high-water bytes; that includes cgroup charges/page
cache, not just Python RSS, and is not a Railway measurement. Missing measurement is labeled
NOT AVAILABLE. See [the follow-up report](P18_BOOTSTRAP_FIX_REPORT.md) for actual results.
