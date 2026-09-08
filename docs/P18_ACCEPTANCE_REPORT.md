# P18 acceptance report — 2026-09-08

**P18 implementation ready; cloud/auth configuration pending.**

No actual Auth0 login, GitHub-hosted Actions run, Railway deployment or Vercel deployment was
performed. These are **NOT VERIFIED**, not inferred from mocks or local containers. No P19,
staging, commit, push, paid resource creation, booking or payment work was performed.

## Git gate and scope

The initial working tree was clean on `main`, HEAD `aa5d8aa`, the committed P17 milestone
`feat: integrate multi-provider travel search`. Fetch found two remote README-only commits.
The prompt-authorized `git pull --ff-only origin main` advanced to `31007f8` through `94d52f6`.
The P18 implementation baseline is therefore `31007f8`; no history was rewritten.

Only P18 authentication, user scoping, rate admission, frontend session wiring, deployment,
CI, tests and related documentation changed. Docker Compose, provider adapters, graph topology,
travel domain facts, review loop and existing SSE business event protocol were not rewritten.

## Executed commands and results

| Command | Actual local result |
|---|---|
| `uv sync --locked` | PASS; 167 resolved, existing local installation checked |
| `uv run ruff check .` | PASS, All checks passed |
| `uv run ruff format --check .` | PASS, 379 files already formatted |
| `uv run mypy app` | PASS, 169 source files |
| `uv run pytest tests/auth tests/deployment -q` | 93 passed |
| `uv run pytest -q` | 714 passed, 17 skipped |
| `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q` | 11 passed, 1 skipped, 719 deselected |
| `uv run python scripts/check_infra.py` | PostgreSQL accepting connections; Redis PONG; Chroma HTTP 200, executor/log client ready |
| `npm ci` in frontend | PASS; 264 installed, 265 audited, zero reported vulnerabilities |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run test:run` | 77 passed in 14 files |
| `npm run build` | PASS; 1905 modules; nonfatal main-JS size warning (527.22 kB) |
| `npm run test:e2e` | 2 passed, 2 real-browser cases skipped |
| Production frontend build with public example Auth0/API values | PASS, 1905 modules, 527.58 kB JS; local compile only, no login or deployment |
| `docker build -t travel-planner:p18 .` | PASS; pinned Python 3.12.14, uv 0.12.2; Linux CPU Torch |
| `uv run python scripts/check_deployment.py` | Local demo health, ready, prepared RAG, Agent plan, restart and SIGTERM checks |
| Deployment config tests | Railway TOML, Vercel JSON and CI YAML parsed; local contract assertions passed |
| `git check-ignore .env` | `.env` remains ignored; its contents were not printed |

Ordinary pytest, local integration and container acceptance made no real Auth0, Qwen, Duffel
or LiteAPI requests. Existing real-service tests remained explicitly gated. Public documentation,
Git fetch, dependency/registry downloads and build-time model downloads are distinct from API
acceptance and were not represented as travel/LLM test success.

The local Docker credential helper initially stalled. An empty temporary CLI config with the
existing Docker Desktop socket avoided the helper without changing saved Docker credentials.
The default Linux dependency resolution also included unnecessary CUDA packages; the verified
official Linux CPU index was selected and locked. The first CUDA build was stopped, not counted
as successful. A local checker initially reused a stale randomly published port after restart;
re-reading Docker's current port fixed that checker failure. Neither issue was hidden.

## Security review and fixes

No unresolved Critical, High or Medium issue was identified in this local review. This is not a
penetration test, provider security certification or production-readiness claim.

| Severity | Finding addressed during implementation | Status / evidence |
|---|---|---|
| High | Reusing demo client identity/thread keys would allow cross-user access | Fixed at every protected boundary: verified principal, scoped checkpoint/Store keys, two-user RSA/API/SSE tests |
| High | A public demo-auth image or public docs/metrics would be unsafe defaults | Image defaults production/Auth0 with docs/metrics off; production Settings reject unsafe combinations |
| Medium | Socket-only JWKS timeout can be extended by a trickling response | Total async deadline added; cancellation and deadline regression |
| Medium | Per-user intake alone does not cap multi-account model spend | Added separate atomic global daily intake cap as well as global plan cap; no disable switch in Auth0 mode |
| Medium | Verifier close failure could skip unrelated pool cleanup | Nested finally; regression proves PostgreSQL/Redis/Chroma cleanup still happens |
| Medium | Logout or token acquisition race could send a request under an obsolete UI session | Workspace unmount/abort and post-token signal check; mocked UI/client tests |
| Low | Internal preference source checkpoint prefix in an own-user response | Public-ID projection at API boundary; regression checks exact original public ID |
| Low | Main frontend JS exceeds default 500 kB warning threshold | Not expanded into a code-splitting refactor in P18 |

JWT validation uses fixed RS256 and configured issuer/API audience, not token-supplied algorithms
or remote URLs. Unknown kid refresh, malformed/oversized JWKS, rotation, outage cooldown and
concurrent caching are tested without Auth0. Missing resources do not probe another user scope.
Authentication/authorization/rate counters have bounded categories and no identity labels.

### Secret/artifact checks

- Actual `.env` is ignored, not tracked or staged; only `.env.example` templates are candidates.
- Git candidate paths contained no real env, model cache, node_modules, dist or generated data.
- A common key/JWT-shape scan found three **unchanged pre-P18 negative-security test files**:
  `tests/intake/test_qwen_extraction.py`, `tests/intake/test_service.py`,
  `tests/llm/test_grounding.py`. Redacted inspection showed their dedicated prompt-injection /
  credential-redaction tests, not newly added credentials. Matching values were withheld.
- Built frontend files had zero matches for the checked secret shapes or backend credential
  variable names. Public Auth0 domain/client ID/audience/API URL are intentionally not secrets.
- Image config was inspected internally and contained no backend credential variables. Dockerfile
  uses explicit copies, no secret build args, no real `.env`, and runtime UID/GID `10001:10001`.
- These targeted scans are not proof against every possible secret format or future misconfiguration.

## Required final-report checklist

“LOCAL VERIFIED” below means executed tests/commands or direct source/config inspection. It does
not mean a configured real identity provider or deployed cloud service.

| # | Item | Result / boundary |
|---|---|---|
| 1 | Starting HEAD | `aa5d8aa`; authorized clean fast-forward baseline `31007f8` |
| 2 | P17 commit | Verified `aa5d8aa` in history |
| 3 | Initial working tree | Clean; main matched remote after fast-forward |
| 4 | Auth architecture | Local demo preserved; Auth0 mode protects all application routes |
| 5 | Auth0 React SDK | Locked `@auth0/auth0-react` 2.24.1 |
| 6 | JWT library | PyJWT 2.13.0 with crypto extra; cryptography 50.0.0 |
| 7 | Issuer | Exact normalized configured HTTPS issuer; no token URL discovery |
| 8 | Audience | Required configured API audience, not SPA profile ID-token audience |
| 9 | Algorithm | RS256 only, RSA public keys 2048–8192 bits; none/HS256 rejected |
| 10 | JWKS cache | Lifespan async pool, TTL 3600s default, 64 KiB/32 keys, lock, total/socket timeout |
| 11 | Unknown kid | One forced refresh followed by shared 30s cooldown; cold-cache one fetch |
| 12 | Principal | Frozen minimal subject/user_ref; subject excluded from repr |
| 13 | user_ref | Stable domain-separated issuer/subject SHA-256; pseudonymization, not encryption |
| 14 | Legacy user_id | Ignored for Auth0 ownership; existing demo validation retained |
| 15 | Thread scope | `auth0:<user_ref>:<public_thread_id>` checkpoint key; public IDs unchanged |
| 16 | Isolation | Offline two-user same-thread state/history/intake/reset/SSE/preferences tests PASS |
| 17 | Preferences | `/me/preferences` GET/DELETE; legacy path cannot select another identity |
| 18 | Protected routes | Plans, streams, conversation, preferences, RAG and diagnostics |
| 19 | Public routes | health/ready safe summaries; local-only optional docs/metrics |
| 20 | Diagnostics | Auth0 token required for RAG/MCP/LLM/travel-data status |
| 21 | Metrics | Public endpoint disabled in production; existing local observability preserved |
| 22 | Docs/OpenAPI | Disabled in production; reject unsafe production Settings |
| 23 | Rate limiter | Redis Lua atomic all-caps check then all-caps increment/expiry |
| 24 | Per-user caps | Intake 10/minute + 50/day; planning 3/day by default |
| 25 | Global cap | 20 plans/day + 200 intake turns/day; request count, not currency guarantee |
| 26 | Redis outage | 503 fail closed before costly graph/intake/SSE work |
| 27 | Auth metrics | Bounded operation/outcome; no token/kid/user/IP labels |
| 28 | Auth logs | No token/claim/profile logging added; existing safe HTTP outcomes retained |
| 29 | Login | SDK Universal Login/PKCE wiring and mocked UI PASS; real login NOT VERIFIED |
| 30 | Logout | Unmount, cancellation, own local-pointer cleanup and SDK logout; no backend deletion |
| 31 | Profile | Browser-only safe React text display; not added to graph/checkpoint |
| 32 | Token storage | SDK memory cache; no app token localStorage/sessionStorage/IndexedDB |
| 33 | API header | Central request client gets SDK access token; Bearer header tested |
| 34 | SSE header | Existing POST fetch/ReadableStream gets Bearer header; no native EventSource body claim |
| 35 | 401 | Safe sign-in-again guidance, no automatic mutation replay |
| 36 | 403 | Safe access-denied guidance, no automatic replay |
| 37 | localStorage | Authenticated account hash scopes thread/recent metadata; demo key not used as auth |
| 38 | Demo compatibility | All previous offline backend/frontend tests still pass |
| 39 | CORS | Exact origins, auth headers, request ID exposure; no wildcard/cookie credentials |
| 40 | Trusted hosts | Explicit API/healthcheck hosts; hostile Host rejected |
| 41 | Security headers | nosniff, no-referrer, restricted camera/mic/location; no untested CSP |
| 42 | Production validation | Auth0, origins/hosts, docs/metrics, credentials and direct backend enforced |
| 43 | Backend secrets | Runtime settings only; no Docker args, browser variables or checked-in secret values |
| 44 | Frontend public env | Mode, domain, SPA client ID, API audience and HTTPS API base only |
| 45 | Dockerfile | Official pinned base/uv digests, locked CPU deps, prepared pinned model, non-root |
| 46 | Image size | Measured local image approximately 796 MB; exact final value in container result below |
| 47 | Build | LOCAL VERIFIED; no Railway remote build claimed |
| 48 | Container test | LOCAL VERIFIED demo health/ready/RAG/Agent/restart/shutdown |
| 49 | Railway config | Root Dockerfile, single replica, /ready, start bootstrap; parsed/contract-tested |
| 50 | Railway API | One private-dependency API service documented; actual service NOT VERIFIED |
| 51 | PostgreSQL | Private service variables/persistence documented; cloud NOT VERIFIED |
| 52 | Redis | Private password/optional ACL/TLS settings documented; cloud NOT VERIFIED |
| 53 | Chroma | Separate pinned 1.5.9 private service documented; cloud NOT VERIFIED |
| 54 | Chroma volume | `/data` runtime volume documented; cloud mount/ownership NOT VERIFIED |
| 55 | RAG model | Same multilingual MiniLM, revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 baked in; runtime offline |
| 56 | Bootstrap | Advisory lock, official LangGraph setup, add-only index reconciliation, parent/manifest restore |
| 57 | Healthcheck | /ready before activation; Railway healthcheck host documented; local PASS |
| 58 | PORT | Validated 1–65535; actual container tested at internal port 8080 |
| 59 | SIGTERM | Resource shutdown marker plus non-killed exit checked locally |
| 60 | Vercel | frontend root, Vite install/build/dist, SPA rewrite and headers; local config tests |
| 61 | Frontend API base | Exact HTTPS base required for Vercel production; relative local Vite proxy retained |
| 62 | Auth0 origins | Callback/logout/web-origin local and exact production checklist documented |
| 63 | GitHub Actions | PR and main push workflow exists; actual hosted execution NOT VERIFIED |
| 64 | Backend CI | Python3.12 + uv locked sync, Ruff, mypy, pytest; local equivalent PASS |
| 65 | Frontend CI | Node24 + npm ci, lint/types/tests/build; local equivalent PASS |
| 66 | Playwright CI | Chromium install + mock E2E command configured; local 2 PASS, 2 gated skips |
| 67 | Workflow permissions | contents:read only; official actions pinned to verified 40-character SHAs |
| 68 | CI isolation | No provider secrets; deterministic/demo, offline model env and transport gates |
| 69 | Targeted auth tests | 83 offline auth tests included in 93 auth/deployment PASS |
| 70 | Authorization tests | Actual generated RSA + signed local tokens, two scopes and spoofed client IDs |
| 71 | Rate tests | Pure windows/response checks + real Redis concurrent Lua/global cap/TTL |
| 72 | CORS tests | Allowed/rejected preflight, auth headers, expose headers, local compatibility |
| 73 | Backend regression | 714 passed, 17 skipped |
| 74 | Frontend regression | 77 unit PASS; lint/types/build PASS; 2 E2E PASS, 2 skipped |
| 75 | Local integration | 11 passed, 1 skipped, 719 deselected; no paid real requests |
| 76 | Actual Actions | NOT VERIFIED; no push performed |
| 77 | Real Auth0 local login | NOT VERIFIED; dashboard configuration pending |
| 78 | Real two-user auth | NOT VERIFIED; cryptographic offline counterpart PASS |
| 79 | Railway deployment | NOT VERIFIED; no account resources created |
| 80 | Vercel deployment | NOT VERIFIED; no deployment created |
| 81 | Deployed HTTPS | NOT VERIFIED; no public URL invented |
| 82 | Deployed health | NOT VERIFIED; local container health PASS only |
| 83 | Deployed ready | NOT VERIFIED; local container readiness PASS only |
| 84 | Deployed login | NOT VERIFIED |
| 85 | Deployed authenticated API | NOT VERIFIED |
| 86 | Deployed SSE | NOT VERIFIED; offline authenticated POST SSE PASS |
| 87 | Deployed persistence/restart | NOT VERIFIED; local backend restart/RAG reuse PASS |
| 88 | Chroma persistence | Local retained named volume/restart reuse PASS; cloud NOT VERIFIED |
| 89 | Public-service audit | Local DB/Redis/Chroma loopback-only; cloud public-proxy audit NOT VERIFIED |
| 90 | Frontend secret scan | Checked generated files: no backend key-variable names/common credential/JWT shapes |
| 91 | Repository secret scan | No forbidden generated/env paths; only unchanged known negative-test literals matched |
| 92 | Critical findings | None unresolved identified in local review |
| 93 | High findings | None unresolved identified; identity/default hardening covered above |
| 94 | Medium findings | None unresolved identified; deadline/cost/cleanup/cancel fixes covered above |
| 95 | Fixes | Regression tests included; no real Auth0/cloud claims inferred |
| 96 | Limitations | Account gates, no hard monetary cap, no multi-worker same-thread lock, no replay/token streaming |
| 97 | Process cleanup | Temporary API container removed; application ports/MCP checked at handoff |
| 98 | Volumes | Existing postgres/redis/chroma/prometheus/grafana named volumes preserved |
| 99 | Git | P18 files unstaged; HEAD 31007f8; final filename inventory below |
| 100 | P19 | Explicitly not entered |
| 101 | Suggested commit | `feat: add secure auth and cloud deployment` — suggest only |

## Exact remaining manual gate

Follow [the beginner deployment guide](25_AUTH_AND_DEPLOYMENT.md), sections 7–12, in order:

1. User configures an Auth0 SPA and RS256 API. Share only public domain/client ID/audience if
   assistance is needed. No client secret belongs in this SPA.
2. Verify real local login, authenticated intake/planning/reload/logout and, if available, two
   accounts using one public thread ID. Do not paste JWTs into the terminal or conversation.
3. User decides whether/when to commit and push, then observes the actual Actions run. Local
   checks do not satisfy that gate. Enable Railway **Wait for CI** only after account setup.
4. User provisions budget-reviewed Railway private PostgreSQL/Redis/Chroma (Chroma `/data`
   volume), configures production API variables and deploys the backend.
5. User configures Vercel frontend public variables and the three Auth0 allowed-origin fields,
   plus backend exact CORS/trusted hosts. Verify HTTPS and protected JSON/POST SSE.
6. Verify persistence after backend restart, Chroma volume persistence and no public database,
   Redis, Chroma, metrics or OpenAPI exposure. Record actual URLs/results only after execution.

Current operational limitations include single API worker/replica, no distributed same-thread
mutation lock, request-count rather than currency caps, possible fixed-window boundary bursts,
no self-service migration of demo identities, and no server-side recent-thread discovery after
local logout metadata is cleared. Model preparation needs build networking; model runtime does
not download. Existing no-booking, test/sandbox provenance, no Last-Event-ID replay and no actual
model-token streaming boundaries remain unchanged. No production-readiness claim is made.

## Final container output and Git inventory

Final image: `fdb295bc36fc` (`travel-planner:p18`). Actual sanitized checker output:

```text
PASS container: health, readiness, prepared RAG and deterministic Agent plan
PASS container restart: same RAG status; idempotent bootstrap
PASS container shutdown: application resources closed after SIGTERM
INFO image size bytes: 796042548
INFO image runtime user: 10001:10001
PASS image environment: no backend credential variables
PASS cleanup: temporary API container removed; named volumes retained
```

Local service state: PostgreSQL `postgres:16.14-alpine` healthy on loopback 5432;
Redis `redis:7.4.9-alpine` healthy on loopback 6379; Chroma `chromadb/chroma:1.5.9`
running on loopback 8001, with independently successful v2 health check.

Retained Compose volumes:

```text
ai_travel_planner_codex_pack_chroma_data
ai_travel_planner_codex_pack_grafana_data
ai_travel_planner_codex_pack_postgres_data
ai_travel_planner_codex_pack_prometheus_data
ai_travel_planner_codex_pack_redis_data
```


Git status inventory: **30 modified tracked + 36 new untracked files = 66 files**.
`git diff --stat` reports only the 30 already tracked files (556 insertions, 349 deletions);
it does not count the 36 new files until they are staged. Nothing is staged here.

```text
 M .env.example
 M README.md
 M app/api/routes/conversation.py
 M app/api/routes/persistence.py
 M app/core/config.py
 M app/core/lifespan.py
 M app/infrastructure/redis.py
 M app/main.py
 M app/rag/embeddings.py
 M app/rag/runtime.py
 M app/schemas/intake.py
 M app/schemas/persistence.py
 M docs/implementation-notes.md
 M frontend/.env.example
 M frontend/package-lock.json
 M frontend/package.json
 M frontend/src/App.tsx
 M frontend/src/api/client.ts
 M frontend/src/api/conversation.ts
 M frontend/src/api/streaming.ts
 M frontend/src/hooks/useConversation.test.tsx
 M frontend/src/hooks/useConversation.ts
 M frontend/src/hooks/useLocalIdentity.ts
 M frontend/src/hooks/usePlanningStream.ts
 M frontend/src/lib/storage.ts
 M frontend/src/main.tsx
 M frontend/vite.config.ts
 M pyproject.toml
 M tests/conftest.py
 M uv.lock
?? .dockerignore
?? .github/workflows/ci.yml
?? Dockerfile
?? app/auth/__init__.py
?? app/auth/configuration.py
?? app/auth/dependencies.py
?? app/auth/headers.py
?? app/auth/rate_limit.py
?? app/auth/tokens.py
?? app/deployment/__init__.py
?? app/deployment/bootstrap.py
?? app/deployment/prepare_model.py
?? app/deployment/start.py
?? docs/25_AUTH_AND_DEPLOYMENT.md
?? docs/P18_ACCEPTANCE_REPORT.md
?? frontend/src/auth/AuthRoot.test.tsx
?? frontend/src/auth/AuthRoot.tsx
?? frontend/src/auth/config.test.ts
?? frontend/src/auth/config.ts
?? frontend/src/auth/context.ts
?? frontend/src/auth/requests.test.ts
?? frontend/vercel.json
?? railway.toml
?? scripts/check_deployment.py
?? tests/auth/__init__.py
?? tests/auth/conftest.py
?? tests/auth/test_api.py
?? tests/auth/test_configuration.py
?? tests/auth/test_lifespan.py
?? tests/auth/test_rate_limit.py
?? tests/auth/test_tokens.py
?? tests/deployment/__init__.py
?? tests/deployment/test_artifacts.py
?? tests/deployment/test_bootstrap.py
?? tests/deployment/test_checker.py
?? tests/integration/test_auth_rate_integration.py
```

Final checks: `git diff --check` clean; no staged filenames; HEAD remains `31007f8`.
Local Node is 24.20.0, npm/npx 11.19.0, uv 0.12.2, Docker Compose 5.3.1.
The temporary failed-build container and empty temporary Docker CLI config were removed;
no images or named volumes were deleted. MCP subprocess count and listeners on 5173/8000/9001
were zero. The final Auth0-example frontend bundle scan also found zero credential matches.
