# P19 — Local Acceptance and Publication Handoff

日期：2026-09-15。项目：AI Travel Planning Agent。

**P19 local integration verified; ready for controlled publication.**
**Cloud acceptance and publication pending.**

本报告已补入同日“发布前本地集成验证”结果；不是新一轮开发或云部署。
保留全部既有 P19 修改；本次恢复时为 49 tracked modified + 18 untracked，HEAD 未变。

本次补验只新增/调整以下文件，其余 P19 改动原样保留：

- 测试隔离：`tests/conftest.py`、`tests/local_infrastructure.py`、
  `tests/deployment/test_local_integration_settings.py`。
- PostgreSQL 证据：`tests/auth/test_p19_isolation.py`、
  `tests/integration/test_p19_product_quality_integration.py`。
- 旧集成断言：`tests/integration/test_mcp_integration.py`、
  `tests/integration/test_review_integration.py`、`tests/integration/test_streaming_integration.py`。
- 记录：本报告、`docs/26_PRODUCT_QUALITY_AND_HANDOFF.md`、
  `docs/implementation-notes.md`、`README.md`。

没有额外修改应用实现、前端代码、Dockerfile、依赖锁或 Compose。

## A. 已完成的实现与恢复现场

开始及最终 HEAD：`6bc79ba3c97f4b6fd966a7d5dc5b010e9088ecf2`。
分支为 main；本地缓存的 origin/main 指向同一提交，本轮未 fetch，因此不是远端实时查询结果。
最近三次提交为 README P18 验收记录、bounded bootstrap 修复、P18 auth/deployment。

这是同一 P19 工作树的续跑。恢复时先读取 status/log/diff check/stat/name-status/untracked：
46 个已跟踪文件修改、14 个新文件（逐个文件计，不把 docs/images 目录当作一个文件）。
后端/前端修复和测试已保存，三张 JPG 已存在但需要重新查看；交接文档尚未写入。
没有发现无关冲突；没有执行 reset/restore/checkout/stash/clean。只读进程检查先被沙箱拒绝，
通过权限流程重试后确认没有遗留的本轮 Vite/Playwright/pytest/uvicorn 进程。
中断前的命令结果没有直接作为本报告最终结果。

### 修复与材料

- Route：旧 provider 把旅行城市对转换成无地理依据的 Demo 公交时长。现在明确 unavailable，
  第五路与非关键失败语义保留；Planner 和组装器也拒绝旧/注入 route，不再把错误分钟数当事实。
- Quality：新 bounded quality/warnings 由可信后端审核字段派生，accepted 与 forced-finalized
  分开，低分和未解决问题保留。没有降低阈值、改最大轮次或重新调用 graph。
- UI：终态清理 Improving/活动进度，拒绝迟到事件；最终摘要/进度显示同一 62.5，保持来源、
  去程不含返程、酒店晚数和额外费用说明。
- 恢复：新计划经严格 MessagePack 保存/读回；旧字段缺失 checkpoint 通过实际 state/history
  HTTP 读取，quality unavailable、score null、历史 route 警告；读前读后保存值不变。
  禁止 graph 再执行的 mock 断言通过，失败状态不恢复旧成功计划。
- 隔离：两套非空本地 JWT 用户、同 public UUID、conversation/plan/history/preference；
  spoofed user_id 和跨用户删除无效。A 改 London 不改变 B 的 Paris。
- 浏览器：真实 AuthRoot/App + 明确 mock SDK，桌面/手机均验证非空 A/B、同 UUID、登出与切换。
  A 的已收到响应被扣留且忽略 AbortSignal，切到 B 后交付，仍不能污染 B 的对话、计划或 recent title。
- Chroma：本地入口及随 app 打包的私有 CLI，get_collection/get/query，只读摘要/直接向量查询；
  不经 Redis，不写索引、不加载新模型。13 项离线测试包括两个新连接、摘要差异、错误查询、
  真实阻塞子进程超时回收和 stderr 不外泄。
- 三张精选截图已经重新生成并逐张打开检查，均标 Local fixture demonstration。
  README、implementation-notes、质量交接与录制脚本已增量完成；没有视频文件，未宣称已录制。

完整实现说明与运维步骤见 [26_PRODUCT_QUALITY_AND_HANDOFF.md](26_PRODUCT_QUALITY_AND_HANDOFF.md)。

## B. 实际验证结果

### 状态口径

| 标签 | 本报告含义 |
| --- | --- |
| LOCAL VERIFIED | 本轮实际运行的离线/本机检查，不代表公网或供应商成功 |
| USER-REPORTED HISTORICAL | 用户于 2026-09-09 报告的 P18 公网结果，未在 P19 重跑 |
| CLOUD VERIFIED | 本轮没有这一类结果 |
| NOT VERIFIED / NOT RUN | 未授权、基础设施未运行或尚未执行，不得算 PASS |

### 实现续跑时的完整回归（本次补验之前）

| 命令/检查 | 实际结果 |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS；396 files already formatted |
| `uv run mypy app` | PASS；173 source files |
| `uv run pytest -q` | **794 passed, 18 skipped** |
| P19 定向质量/API/隔离/Chroma/扫描测试 | **40 passed, 1 skipped** |
| Chroma helper 独立离线测试 | **13 passed**；不等于真实 Chroma 检索 |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run test:run` | **85 passed，15 files** |
| `npm run build` | PASS；本地假公开 Auth0 配置，生产模式校验启用 |
| `npm run test:e2e` | **6 passed, 2 skipped**；desktop/mobile Chromium |
| `git diff --check` | PASS |
| Repository/bundle bounded scan | PASS；472 text files，0 findings（范围和限制见下节） |
| 实际 bundle 模块来源检查 | PASS；97 个输出模块，无测试/认证 fixture 模块 |
| `.env`、登录态、生成数据忽略规则 | PASS；未读取/打印/提交真实环境文件 |

六个浏览器通过项：正常 accepted、forced-finalized + 刷新、账号切换 + 迟到响应，分别在
桌面与手机 Chromium 执行。不是 Safari/WebKit 验收。两个 skip 是显式关闭的真实后端路径。
后端 18 个 skip 包含原有 17 个显式集成场景与新增的本地 PostgreSQL 隔离分支。

### 发布前补验：最终工作树结果

| 命令/检查 | 本次实际结果 |
| --- | --- |
| `docker --context desktop-linux compose config --quiet` | PASS |
| `docker --context desktop-linux compose up -d --wait --wait-timeout 120 postgres redis chroma` | PASS；仅启动这三个已有服务 |
| `scripts/check_infra.py` | PASS；PostgreSQL accepting connections、Redis PONG、Chroma HTTP 200 ready |
| 现有幂等 `scripts/setup_langgraph_persistence.py` | PASS；没有重置 schema 或历史数据 |
| `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q --tb=short`（真实调用 gates 均关闭） | **15 passed, 1 skipped, 800 deselected** |
| 新增本地环境隔离回归 | **1 passed** |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS；399 files already formatted |
| `uv run mypy app` | PASS；173 source files |
| `uv run pytest -q`（集成/真实调用 gates 关闭） | **795 passed, 21 skipped** |
| `npm run test:run -- src/components/itinerary/QualityAcceptance.test.tsx` | **5 passed** |
| 起始提交旧 Zod + 当前 Zod 的实际 Node wire-schema 比较 | PASS；见兼容矩阵，旧客户端确实拒绝新增字段 |
| 本地生产镜像 build / 2 GiB helper 容器运行 | PASS；见下面镜像证据 |

本次修改 tests/conftest.py 会影响整个后端测试进程，因此重跑全部后端回归。
没有修改前端代码或依赖，未重复完整前端构建/85 项 UI/6 项浏览器回归；这些仍属于上表此前
已执行的本地实现结果，不能写成本次新跑。21 个离线 skip 包括新增的 3 个 PostgreSQL 场景。
集成唯一 skip 是 `RUN_OBSERVABILITY_TESTS=0` 的 P13 观测端到端场景；未启动额外观测服务。

本次补齐的实际 PostgreSQL 证据：

- `tests/integration/test_p19_product_quality_integration.py`：3 项；95 分 accepted、60 分
  forced-finalized 达到既定最大轮数、缺 quality/warnings 的旧 checkpoint。
  每项跨应用 lifespan/数据库连接重开，读取实际 state/history；计划质量和警告一致。
  读阶段禁止 invoke/ainvoke/stream/astream；旧 checkpoint 的 config/values 原样保留，
  不写回伪造质量。严格 MessagePack、无 pickle fallback，重开后 TravelPlan 类型保留。
- 原有 A/B JWT 回归的 PostgreSQL 参数现归入 integration marker，在同一命令中实际执行：
  同 public UUID、不同 subject、非空 conversation/plan/history/preferences、伪造 user_id、
  跨用户删除拒绝、A 改草稿不污染 B。JWKS 使用 MockTransport，并未访问 Auth0。
- MCP、review、SSE integration 现在断言 5 个任务、4 路可用结果、route 非关键 error/warning，
  持久化正常；不是删除失败场景、降低审核阈值或恢复无依据的路线分钟数。

首轮结果为 **3 failed, 9 passed, 1 skipped**：三处旧测试仍要求 route 成功/5 个成功结果。
仅修复这些过时断言、加强失败语义检查并补覆盖；没有改应用算法。首轮失败回收期间还出现
LangGraph AsyncBatched Store 的 pending-task 日志；最后一次完整集成与离线回归未再出现，
没有通过过滤日志、跳过测试或升级依赖消除它；这也不是长期运行资源泄漏验收。

测试安全隔离在 pytest 进程内完成：强制本地回环数据库地址、demo/deterministic、关闭 tracing、
离线模型模式、禁用代理处理 loopback；真实 httpx transport 禁止非回环地址，MockTransport
仍可用于本地 JWT/供应商 fixture。Compose 本地密码/端口由现有设置读取但不打印；真实 `.env`
未编辑，持久化测试仅清理自己生成的 UUID 命名空间；已有 RAG 集成测试另对单个 fixture
检索缓存项做精确失效，以验证真实检索和缓存重填。不清空库/Redis/Chroma，不删除用户历史。

构建仍有大 chunk 提示（JS 531.76 kB，gzip 156.55 kB）；没有为消除提示调高阈值。
这些是本次本地构建产物大小，不是延迟、吞吐或生产容量指标。

### 本轮遇到并解决的验证失败

1. 账号 fixture 最初使用错误的 React 导出/未带版本的模块 URL，导致 Vite 重复 React 实例。
   修正测试替身的 import 后，真实断言通过；没有删除账号切换测试或放宽生产 auth。
2. 本地环境中的真实 Auth0 配置可能影响普通测试。Vitest 与 Playwright 采用测试级隔离。
   组合构建回归还发现 `VERCEL_ENV=production` 继承导致 demo 测试服务器被正确拒绝；
   只在 fixture 服务器隔离该标记，随后全部前端命令重新通过。
3. 截图检查发现同一评分被进度卡取整为 63，而摘要为 62.5；统一实际值并新增浏览器断言。
4. 只读 helper 原先只具备 Unix 信号超时；同步调用可能无法及时响应。增加外层受控进程
   deadline，实际 kill/reap 测试通过。已有镜像不复制 scripts，故将实现放进 app/deployment，
   保留原脚本入口，没有修改启动流程。

### Docker 与真实外部服务

发布前补验已确认 Docker Desktop context 为 `desktop-linux`，endpoint 是本机 Unix socket，
不是远端生产 Docker；client/server 都为 29.6.2。最后 `docker compose ps` 的服务状态为：

```text
SERVICE    IMAGE                    STATUS          PORTS
chroma     chromadb/chroma:1.5.9     Up              127.0.0.1:8001->8000/tcp
postgres   postgres:16.14-alpine     Up (healthy)    127.0.0.1:5432->5432/tcp
redis      redis:7.4.9-alpine        Up (healthy)    127.0.0.1:6379->6379/tcp
```

以上为实际输出的关键列，省略易变的 Up 时长。Chroma 没有容器内 healthcheck，用独立 HTTP
检查验证 executor/log client ready。三个服务保留运行；Prometheus/Grafana 未启动。
五个原有 named volumes 均保留：`ai_travel_planner_codex_pack_` 前缀下的
`postgres_data`、`redis_data`、`chroma_data`、`prometheus_data`、`grafana_data`。
仅移除了本轮临时 helper 容器，其摘要先安全复制到忽略目录；没有删除任何 named volume。

| 项目 | 本轮状态 |
| --- | --- |
| 本地真实 PostgreSQL 双用户隔离 | LOCAL VERIFIED；本地签名 JWT，不是真实 Auth0 云登录 |
| 本地真实 Chroma collection/query | LOCAL VERIFIED；77 条、384 维，镜像内两次读取/比较通过 |
| 真实双 Auth0 用户云验收 | NOT VERIFIED；需用户账号操作与单独授权 |
| 生产 Chroma-only 重启前后比较 | NOT VERIFIED；未获重启授权，尚无基线/后测 |
| P19 公网行为和部署版本 | NOT VERIFIED；P19 未部署，未查询/修改云配置 |
| 真实 Qwen/Auth0/Duffel/LiteAPI 调用 | **各 0 次** |
| 视频 | NOT RECORDED；已有可执行录制脚本 |

P18 的公开登录、JWT API、health/ready、Qwen intake、Duffel Test/LiteAPI Sandbox 结果、
POST SSE、API 重启后 Tokyo 恢复和 hosted CI，仅保留为 **USER-REPORTED HISTORICAL**。
API 重启恢复也不等于 Chroma 自身重启后索引持久化已经验证。

### Chroma 工具的镜像证据与命令

现有 Dockerfile `COPY app ./app` 已包含 `app/deployment/chroma_evidence.py`，但不复制根
`scripts/`。本地入口仍是 `uv run python scripts/check_chroma_persistence.py`；生产镜像入口
必须为 `python -m app.deployment.chroma_evidence`。无需修改 Dockerfile、依赖或启动流程。

本次实际 `docker --context desktop-linux build --tag travel-planner:p19-local .` 成功，镜像 ID
`sha256:aa8d718c5b6798fbd9befdf3735e293188e67aebcd9732dce43e59426550b6e2`。
构建使用现有 Docker Desktop builder（约 8 GiB 可用），**没有声称 builder 被限制为 2 GiB**。
工具运行容器实际 `memory.max=2147483648`（2 GiB、无额外 swap），UID 10001；help 在
`--network none` 容器中成功。镜像包含 module，不包含 scripts wrapper 的文件检查通过。
BuildKit 对 `AUTH_MODE` 给出名字匹配的 secrets lint 提示；它是公开模式名，不是密钥。
正常镜像构建执行既有 pinned 模型预装；**只读工具运行不加载这个模型**。

专用 helper 容器仅接入本地 Compose 网络、不开 API、不执行 bootstrap。使用真实 CLI
before/after 对已有集合读取成功，count=77、dimension=384，ID/sample/metadata/query-anchor
摘要一致；另一次受保护运行将 `SentenceTransformerEmbeddingBackend.load` 设为报错，
仍完成真实 query，且进程未导入 sentence_transformers/torch。生产容量没有因此得到验证。
基线文件权限 0600，只包含摘要；复制保存在本地
`.p19-private/chroma-image-local-before-20260915.json`，Git/Docker context 均忽略。
该基线绑定 `chroma:8000` 和本地 context，**不能用来对比生产或宿主机另一 endpoint**。
两次读取之间没有 Chroma restart，所以工具仍正确输出 `NOT VERIFIED restart`。

本地帮助（已实际执行镜像形式）：

```bash
uv run python scripts/check_chroma_persistence.py --help
docker --context desktop-linux run --rm --network none --memory 2g --memory-swap 2g \
  --entrypoint python travel-planner:p19-local -m app.deployment.chroma_evidence --help
```

**将来授权后，在已部署 P19 的 Railway API 私有容器内执行**（不是在本机 `railway run`）：

```bash
cd /app/data/generated
umask 077
PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence --help
PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence before --baseline .p19-private/chroma-before.json --context p19-production-existing-chroma-volume
# 停止，另行授权并记录 Chroma-only 重启；不重启 API、不触发 bootstrap/indexer
PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence after --baseline .p19-private/chroma-before.json --context p19-production-existing-chroma-volume
```

快照位于 `/app/data/generated/.p19-private/chroma-before.json`，API 容器替换后可能丢失，
因此 before 成功后先通过已授权 SSH/SFTP 导出单个摘要文件。连接、传出命令与停止条件见
[交接文档](26_PRODUCT_QUALITY_AND_HANDOFF.md) 的“生产执行位置与步骤”。
此处只证明镜像打包和本地运行；当前 Railway 已部署镜像是否包含 P19、SSH 权限/私网访问、
生产 before/after 均 **NOT VERIFIED**。60 秒信号 + 70 秒父进程 kill/reap deadline 已保留，
不是“停止等待便能强制取消同步调用”，也不是硬实时保证。

### 图片证据

| 实际路径 | 像素 | 最后检查 |
| --- | --- | --- |
| [images/p19-01.jpg](images/p19-01.jpg) | 1280 × 983 | 对话、补充需求与确认，无私密身份信息 |
| [images/p19-02.jpg](images/p19-02.jpg) | 1280 × 1090 | 五路及 route failure、审核中；中间态才显示 Improving |
| [images/p19-03.jpg](images/p19-03.jpg) | 1280 × 2736 | 62.5 分强制结束草稿、来源/费用限制；无 Improving/活动 spinner |

均为实际本地应用 fixture 截图，不是新一次 provider 或云验收。逐张检查无明显裁切遮挡、
邮箱、凭据或可用认证状态。健康 Connected 也是 fixture，不是登录证明。
第三张全页图较长，可打开原图。仅这三张进入待审文件；原始 trace/HAR/登录态/测试输出不在 Git。
[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md) 提供约 100 秒脚本和重新生成步骤。

## C. 安全复核、交接与 Git

### Findings（按严重程度；此处针对本轮，不是完整渗透测试）

| 程度 | 问题 | 处理 |
| --- | --- | --- |
| Critical | 本轮检查未发现 | 不表示系统不存在其他风险 |
| High | 无依据 Demo route 进入规划事实，可能误导旅行可行性 | 已修复；多层阻断，保留第五路非关键失败 |
| Medium | workflow 结束/forced-finalize 可能呈现为 accepted 或继续 Improving | 已修复；后端摘要 + UI 终态与迟到事件保护 |
| Medium | 旧 checkpoint/刷新可能缺失审核信息或误恢复旧成功计划 | 已修复；unknown 历史警告、失败 state 不恢复、只读回归 |
| Medium | 旧账号异步结果晚到可能写入当前页面/recent metadata | 已修复；当前请求/卸载检查及桌面手机回归 |
| Medium | 测试继承真实 auth 配置、错拦源码模块或重复 React，使验收不可信 | 已修复；配置/路径/模块隔离，未跳过核心断言 |
| Medium | Chroma 检查缺少强制截止和准确生产执行入口 | 已修复；专用模块及受控 worker deadline，生产运行仍未验证 |
| Low | 前端大 chunk 提示 | 未扩大为拆包重构；保留提示 |

没有已知未修复的本轮 Critical/High/Medium 代码问题。真实配置可能渗入本地集成测试的
Medium 风险已用进程级隔离和本地 transport 限制处理；测试覆盖缺口也已补齐。
旧密钥撤销已获用户确认，但云授权和云验收仍是待办，不能写成“公网已修复”。

### 安全扫描证据与限度

- 首轮候选发现：旧 dist 的 private-key 分隔符，以及三个后端安全测试的合成 key 形状。
  已定位合成值用于测试 prompt/错误输出脱敏；RSA 登录测试密钥在测试进程生成，不落盘。
- **没有以字符串拼接规避扫描作为安全结论**。重新执行 production-mode build，用 Vite
  `build(write:false)` 收集实际 chunk.modules，并逐个 JS chunk 与 dist 字节比较，全部相同。
  97 个输出模块中没有 src/test、tests、.auth、Playwright 状态或 test/spec 模块。
- 完整 PEM、合成 credential、mock SDK 账号标记均不在产物。PEM 分隔符的实际来源模块是
  `@auth0/auth0-react/dist/auth0-react.esm.js` 中的密钥格式解析逻辑；安装的 JOSE importPKCS8
  也仅检查该分隔符，不包含静态私钥。
- 产物只含五个允许的 VITE 配置名：AUTH_MODE、API_BASE_URL、AUTH0_DOMAIN、AUTH0_CLIENT_ID、
  AUTH0_AUDIENCE（均带 VITE_ 前缀）。没有把后端秘密引入前端。
- `check_public_artifacts.py` 扫描 Git 已跟踪/未忽略候选及实际 dist，输出类别/文件/行号，
  不输出命中内容；真实环境/私有文件先按路径拒绝而非读取。图片另行人工检查。
- 当前候选中没有真实环境文件、模型缓存、测试生成数据库、Cookie、HAR、trace、登录态；
  ignore 检查通过。没有打印真实 key 或完整环境文件。没有上传 CI artifact。
- 这是有界格式/来源检查，不是 Git 历史全扫描，不保证覆盖所有形式的秘密。

| 历史凭据 | 撤销确认 |
| --- | --- |
| Qwen key | **USER CONFIRMED revoked — 2026-09-15** |
| Duffel token | **USER CONFIRMED revoked — 2026-09-15** |
| LiteAPI key | **USER CONFIRMED revoked — 2026-09-15** |

用户本次明确确认三家曾暴露的旧凭据均已撤销，Railway 和本地使用替换后的凭据。
这是用户确认记录，不是代理访问供应商控制台的独立验证；未提取、打印、复用或轮换任何值。
此前 NOT CONFIRMED 已由本次明确确认取代；仓库扫描本身不能证明撤销。

### 最少用户操作与安全发布顺序

1. Review 当前未提交 P19 diff；上述旧凭据撤销已由用户确认，不把新值发到聊天。
2. 用户另行批准发布窗口。**先新前端、刷新/关闭旧标签页（必要时短维护）、再新后端**。
   新前端兼容旧字段缺失；旧严格 Zod 前端已实测拒绝新字段。其他严格消费者也需先升级。
3. 在正确 P19 revisions 上做真实双用户非空数据验收；只运行获准的 provider/Qwen flow，
   不为高分循环重试，不提高限额。读 state/history/刷新不应重新执行图。
4. 另约 Chroma-only 维护窗口，按交接文档在已授权私网 API 容器中 before → 用户只重启
   Chroma → after。保留 volume；独立记录没有 API bootstrap/reindex，否则仍 NOT VERIFIED。
5. 云结果与 README 一致后再录真实视频/发布。回滚时先后端，保留兼容的新前端。

不能强制所有已打开浏览器自动升级。请安排受控短维护窗口，通知用户关闭/刷新旧标签页，
确认实际加载的新前端 revision 后再切后端；无法确认的旧标签页可能出现解析失败。
本地测试不能替代真实双用户和部署后浏览器验收。

| 前端 / 后端 | 实际证据 | 发布判断 |
| --- | --- | --- |
| 新 / 旧 | Node 加载当前 schema 解析旧 payload，quality=null、warnings=[]；定向 UI 测试显示 Unknown/历史警告 | 可以先发布新前端；未知不能标 accepted |
| 新 / 新 | 当前 schema 接受 accepted/forced-finalized plan 与最终 SSE；5 项 UI 测试；3 项真实 PG 重开用例；此前 fixture 刷新 E2E | 本地通过；生产登录/网络/双用户仍需验收 |
| 旧 / 新 | 直接 `git show 6bc79ba:frontend/src/api/schemas.ts`，用已安装 TypeScript 在内存转译，再用实际旧 Zod 解析相同合成 plan/SSE；两种终态均 `unrecognized_keys: quality,warnings` | **不兼容**，state 中嵌套 TravelPlan 同样严格；必须先升级消费者 |

兼容实验没有模拟一个“宽松旧客户端”；实际起始提交旧 schema 对 legacy plan 成功、对新
plan/plan_completed 失败。没有放宽 Zod 或改变 wire contract 来掩盖发布风险。

本轮没有暂存、commit、push、deploy、tag/release、云变量修改、生产 restart、新建真实账号、
生产限流调整、付费模型/旅行调用、历史用户数据/volume 删除，也没有进入 P20。

### 可复现的本地集成命令

在项目根目录，先确认 Docker Desktop 已启动，context inspect 的 endpoint 是本机 Unix
socket；不是本机则停止。下面只启动本项目三服务。失败先查本地服务/端口，不换生产地址。

```bash
docker context show
docker context inspect desktop-linux --format '{{.Endpoints.docker.Host}}'
docker --context desktop-linux compose config --quiet
docker --context desktop-linux compose up -d --wait --wait-timeout 120 postgres redis chroma
docker --context desktop-linux compose ps
export RUN_AUTH0_INTEGRATION_TESTS=0 RUN_LLM_INTEGRATION_TESTS=0 RUN_DUFFEL_INTEGRATION_TESTS=0
export RUN_LITEAPI_INTEGRATION_TESTS=0 RUN_EXTERNAL_AGENT_INTEGRATION_TESTS=0 RUN_OBSERVABILITY_TESTS=0
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

测试会按现有契约使用本地已建好的 RAG 集合/manifest 与缓存模型。缺少这些前提应停止并
记录，不自动清空或重建现有集合；不使用真实外部服务补齐。已有幂等 persistence setup
可在确认本地 hosts 后执行，不删除旧用户数据。任何 before/after 差异、集合不存在/空、
deadline、API instance 变化或无法排除重建，都必须停止，不能重建后声称持久化通过。

### 你可以亲自运行的离线命令

在仓库根目录运行 Python 检查；显式关闭集成 gate 防止继承 shell 的真实调用设置。
成功应看到上表结果；命令不存在是本机工具环境问题，连接外部服务不是普通测试的前提。

```bash
export RUN_INTEGRATION_TESTS=0 RUN_P19_POSTGRES_TESTS=0 RUN_AUTH0_INTEGRATION_TESTS=0
export RUN_LLM_INTEGRATION_TESTS=0 RUN_DUFFEL_INTEGRATION_TESTS=0 RUN_LITEAPI_INTEGRATION_TESTS=0
export RUN_EXTERNAL_AGENT_INTEGRATION_TESTS=0 RUN_OBSERVABILITY_TESTS=0
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
uv run python scripts/check_chroma_persistence.py --help
```

前端以下假公开配置仅用于本地测试/构建，**不能用于部署**。它们不修改 `.env.local`，也不登录。
Playwright 自己为 fixture server 切回隔离 demo 环境；生产 auth 校验本身保持启用。

```bash
cd frontend
export RUN_UI_E2E=0
export VITE_AUTH_MODE=auth0 VITE_AUTH0_DOMAIN=tenant.example VITE_AUTH0_CLIENT_ID=p19-public-fixture
export VITE_AUTH0_AUDIENCE=https://fixture.example VITE_API_BASE_URL=https://api.example VERCEL_ENV=production
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run test:e2e
cd ..
uv run python scripts/check_public_artifacts.py
git diff --check
git status --short
git diff --stat
```

真实 Docker/Chroma/云测试需要单独满足前提和授权，不属于上面普通回归。
完整 before/after 位置、权限、停止条件、超时边界见交接文档；不要使用 down -v。

### 最终文件清单与 Git 状态

共 **53 个 tracked modified + 21 个 untracked 新文件 = 74 个文件**，全部未暂存。
`git diff --stat` 只统计 53 个 tracked 文件，不包含新文件或图片；Codex edited 文件计数
不能代替 Git 候选清单。没有 .env、缓存、原始测试输出或认证状态。

```text
 M .dockerignore
 M .gitignore
 M README.md
 M app/api/routes/persistence.py
 M app/domain/models.py
 M app/graphs/nodes/finalize_plan.py
 M app/graphs/nodes/planner.py
 M app/graphs/nodes/search_worker.py
 M app/review/models.py
 M app/schemas/persistence.py
 M app/services/mock_providers/route_provider.py
 M app/services/planning_service.py
 M app/streaming/mapper.py
 M docs/implementation-notes.md
 M frontend/playwright.config.ts
 M frontend/src/App.tsx
 M frontend/src/api/schemas.ts
 M frontend/src/components/itinerary/ItineraryView.test.tsx
 M frontend/src/components/itinerary/ItineraryView.tsx
 M frontend/src/components/progress/ProgressPanel.tsx
 M frontend/src/hooks/useConversation.test.tsx
 M frontend/src/hooks/useConversation.ts
 M frontend/src/hooks/usePlanningStream.ts
 M frontend/src/state/appReducer.test.ts
 M frontend/src/state/appReducer.ts
 M frontend/src/test/setup.ts
 M frontend/tests/e2e/mock-journey.spec.ts
 M frontend/tests/e2e/real-journey.spec.ts
 M tests/api/test_persistence.py
 M tests/api/test_streaming.py
 M tests/auth/conftest.py
 M tests/conftest.py
 M tests/external/duffel/test_backend.py
 M tests/external/liteapi/test_hotels.py
 M tests/graphs/test_planner.py
 M tests/intake/test_qwen_extraction.py
 M tests/intake/test_service.py
 M tests/integration/test_mcp_integration.py
 M tests/integration/test_persistence_integration.py
 M tests/integration/test_review_integration.py
 M tests/integration/test_streaming_integration.py
 M tests/llm/test_grounding.py
 M tests/llm/test_reviewer_graph.py
 M tests/mcp_tools/test_backend_graph.py
 M tests/mcp_tools/test_servers.py
 M tests/observability/test_instrumentation.py
 M tests/review/test_graph_loop.py
 M tests/review/test_revision.py
 M tests/search/test_backend.py
 M tests/search/test_nodes.py
 M tests/search/test_parallel_graph.py
 M tests/services/test_mock_providers.py
 M tests/services/test_planning_service.py
?? app/deployment/chroma_evidence.py
?? app/domain/quality.py
?? app/review/presentation.py
?? docs/26_PRODUCT_QUALITY_AND_HANDOFF.md
?? docs/DEMO_WALKTHROUGH.md
?? docs/P19_ACCEPTANCE_REPORT.md
?? docs/images/p19-01.jpg
?? docs/images/p19-02.jpg
?? docs/images/p19-03.jpg
?? frontend/src/components/itinerary/QualityAcceptance.test.tsx
?? frontend/tests/e2e/p19-quality.spec.ts
?? scripts/check_chroma_persistence.py
?? scripts/check_public_artifacts.py
?? tests/api/test_product_quality.py
?? tests/auth/test_p19_isolation.py
?? tests/deployment/test_chroma_persistence_check.py
?? tests/deployment/test_local_integration_settings.py
?? tests/deployment/test_public_artifacts_check.py
?? tests/integration/test_p19_product_quality_integration.py
?? tests/local_infrastructure.py
?? tests/review/test_product_quality.py
```

Tracked diff 统计：`53 files changed, 500 insertions(+), 168 deletions(-)`。

仅建议的 commit message（本轮没有执行提交）：

```text
fix: clarify itinerary quality and finalize acceptance checks
```
