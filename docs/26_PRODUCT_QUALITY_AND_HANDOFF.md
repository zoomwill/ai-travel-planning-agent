# P19 — Product Quality and Handoff

AI Travel Planning Agent 的 P00–P19 实现已完成。P19 功能提交为 `73e9933`，用户已报告
发布操作完成（**USER-REPORTED COMPLETE**）。本次仅同步文档，不执行部署或启动下一阶段。
具体云验收不由泛化完成确认推断；本地结果和证据分级见 [P19 acceptance report](P19_ACCEPTANCE_REPORT.md)，演示见
[walkthrough](DEMO_WALKTHROUGH.md)。

## 1. 用初学者的话解释两个问题

### Route：有输出不等于有可靠交通信息

第五路搜索收到的是“旅行出发城市 → 目的地城市”。旧 Demo provider 用字符串种子生成
`public_transit` 的分钟数和价格，并没有地理覆盖、路线或时刻表依据。因此 Cleveland →
Tokyo 的 29 分钟、Shanghai → Paris 的 89 分钟不是可信旅行事实。

P19 在 provider、search worker、Planner 输入和最终组装处阻断这类 route。没有可靠覆盖
就明确 `route_unavailable`，不猜一个新时长，也不根据城市名断言跨洲。第五路仍然调度，
route 仍是非关键失败；Flights/Hotels 仍是关键依赖。当前也不声称验证了某个本地公交路线。
`data_sources.route=demo` 是尝试使用的来源，不是查询成功证明。

### 终态：工作结束不等于审核通过

| 展示 | 含义 |
| --- | --- |
| Workflow ended | 本轮计算结束，不再 Improving 或转圈 |
| Reviewer accepted — verify travel details | 应用控制的审核条件满足，仍须核实旅行事实 |
| Draft generated — review needed | 达到最多审核轮次，保留草稿和未解决问题，不是 accepted |
| Saved draft — historical review unavailable | 没有可靠审核元数据，分数未知，不能补造通过记录 |

新 `TravelPlan.quality` 是现有后端审核状态的投影，不是第二套执行状态机。它含
`review_status / review_rounds / final_score / finalization_reason / issue_codes`。
`warnings` 只使用有限的应用自有代码；不接受任意模型文字、供应商对象或内部异常。
Backend Pydantic 与 frontend Zod 同步，旧记录缺字段有默认值，未知新字段仍严格拒绝。
评分范围 0–100，NaN/Infinity 被拒绝。进度卡和最终摘要保留同一个实际分数，不偷偷取整。

## 2. 恢复、安全和阶段边界

- Finalize 保存摘要；非流式响应、SSE 最终计划、state 和 history 共用展示规则。
- 成功、错误、停止和恢复都让活动进度停下；迟到业务事件不能把终态变回 planning。
- 读取 checkpoint 不重新执行 Planner、Reviewer 或 graph，不调用 Qwen/provider。
- 历史记录只有可信且一致的终态审核信息才可展示 accepted/forced_finalized；缺失或不一致
  就显示 unavailable。没有新 route 警告的历史内容加 `historical_route_unverified`。
  旧文字仍可见且明确不可信，不改写、不删除历史数据。
- 失败 state 即使留有旧 `travel_plan` 也不恢复为成功结果。
- 账号切换或组件卸载后，旧异步请求即使晚到也不能 dispatch 或更新 recent-trip 标题。
- 去程机票不含返程；酒店按当前后端“结束日也计入住宿”的合同展示入住、退房和晚数；
  LiteAPI exact Decimal total 不用前端乘法重新估算；排除的到店费用仍提示。
- 五路 Send、单次 graph、grounding/候选 ID/数量限制、严格 MessagePack、Auth0 namespace、
  fallback 默认关闭、限流、guest nationality、来源披露均未放宽。
- 没有新增供应商、真实库存、booking/payment、token streaming 或 SSE replay 能力。

## 3. 两个用户的隔离证据

本地 Python 测试为 A/B 在内存中生成 RSA 测试密钥，通过实际 TokenVerifier 验证 JWT；
JWKS 使用 MockTransport、issuer/audience 使用 `.example`。A/B 使用不同 subject 和同一个
public thread UUID，各有非空 conversation、plan、history、preference。验证伪造
body/query/path `user_id` 不能改变身份，跨用户 preference 删除失败，A 改 London 不改变 B
的 Paris。测试密钥不落盘、不进入前端，不是生产凭据。

浏览器测试是 **mock SDK fixture**，不是 Auth0 云验收：真实 AuthRoot/App + 测试 SDK 返回
不同账号和假 bearer 值，API fixture 严格要求对应身份。A 的 Tokyo 和 B 的 Paris 非空；
同一 public UUID 的 recent metadata 分开；切换、登出均移除旧 UI。
故意扣留已经收到的 A POST response，并忽略其 AbortSignal，切换 B 后才交付，验证旧响应
仍不能写回 conversation、plan 或 recent title。React 替身复用 Vite 的同版本模块 URL。
API 拦截限定 `/api/v1/`，不误拦 `/src/api/`；普通 Playwright/Vitest 不继承真实 Auth0 模式。

### 可选本地 PostgreSQL 分支（发布前补验 LOCAL VERIFIED）

仅当你已启动本地 Docker/PostgreSQL 时，在项目根目录运行：

```bash
RUN_P19_POSTGRES_TESTS=1 uv run pytest tests/auth/test_p19_isolation.py -q
# PostgreSQL 分支也已纳入统一的本地 integration 命令：
RUN_INTEGRATION_TESTS=1 uv run pytest -m integration -q
```

此命令检查真实本地持久化，成功时两个存储分支均通过。它拒绝非 localhost 数据库，
只清理自己随机生成的测试命名空间；不会清空表或 volume。连接失败先检查本地容器和端口，
不要替换成生产 DSN 来“解决”。

2026-09-15 补验实际为 15 passed、1 skipped（独立观测 gate 关闭）。三个基础服务已启动，
未启动额外观测服务；数据库 hosts/外部 provider 模式由测试进程隔离，不编辑真实环境文件。
新增 3 个真实 PostgreSQL 重开场景证明 accepted、forced-finalized、旧 checkpoint 的
quality/warnings 保存与只读恢复，禁止读阶段 graph 重跑；完整证据和安全 gates 见验收报告。

### 真实双用户云验收（NOT VERIFIED；需另行授权）

当前只有本地 JWT/PostgreSQL 和浏览器 fixture 的逐项证据。整体发布完成确认没有提供
两个真实账号、同 UUID、非空数据、跨用户操作及账号切换的结果，因此仍是未有证据确认，
不是断言用户未做过或测试失败。以下保留为需要时的验收步骤，本次不执行。

由用户控制两个现有测试账号分别登录，不创建账号，不粘贴密码、JWT、Cookie。
关闭 trace/HAR/video/自动失败截图。使用分离的浏览器 profile，并只记录 A/B 别名和结果。

1. 确认已部署的前后端 revision 都属于 P19，先验证 health/ready 和正常登录。
2. 为两账号选同一个仅用于验收的 public UUID，各保存不同城市的非空 conversation、plan、
   history 和显式 preference。通过受授权的浏览器测试 harness 取得 SDK token，仅内存使用。
3. 验证 A/B 各只能读自己的内容；A 改草稿后 B 不变；伪造 body/query/path 的 user_id 无效；
   B 删除 A preference 返回拒绝/不存在，A 的数据仍在。相同 UUID 返回“自己的数据”也是正确的，
   并不要求一律 403。
4. 同一浏览器切换账号，确认 conversation、plan、recent trips 无旧内容；再登出确认隐藏。
5. 只记录状态码、非敏感断言、revision/时间和别名。遇到泄漏、意外付费请求、限流或异常就停止，
   不循环生成行程、不提高生产限额、不导出 token cache。真实 harness/执行仍待授权准备。

## 4. 只读 Chroma 前后比较

入口：本地 `scripts/check_chroma_persistence.py`；可部署模块
`app/deployment/chroma_evidence.py`。后者位于现有 Dockerfile 的 `COPY app` 范围内，
没有修改容器启动流程，也不导入 FastAPI lifespan。

使用官方 [Client API](https://docs.trychroma.com/reference/python/client) 的 `get_collection`
读取现有集合，并按 [Collection API](https://docs.trychroma.com/reference/python/collection)
执行 count/get/query；指定 `embedding_function=None`，使用已存向量查询，不加载第二个模型。
没有 get_or_create、upsert、reset、索引修复或 Redis 查询。

每次新建客户端，读取全部 ID（最多 4096、每页 128），比较 count/排序 ID SHA-256/集合
metadata/固定前五条 document+metadata 摘要。直接 query 同一个规范 ID 的原始向量，
验证有限距离、有效结果数、ID 属于原集合且包含 anchor。允许近似排序和浮点差异，
不要求邻居逐位相同。这里只抽样内容，不声称所有文档字节均被比较。
还校验现有集合的 pipeline 及其 ID 与本地纯语料构造一致；不构建索引、不生成向量。
模型名称/revision 摘要来自当前配置，不证明存储向量的历史模型来源。

输出只有 count、维度、时间、布尔值和摘要；不打印文本、向量、地址或 DSN。
baseline 必须位于 `.p19-private/`，创建时拒绝覆盖，读取大小限制 32 KiB。
before/after 必须使用同一非敏感 context 标签和 endpoint/collection 配置。

### 截止机制的真实边界

支持 macOS/Linux。工作子进程设置 60 秒 SIGALRM；同步客户端本身没有可依赖的逐请求
timeout 设置，信号也可能等待 C 扩展返回。**仅停止等待或取消线程不能强制终止同步请求**。
因此外层用 `subprocess.run(timeout=70)` 监督：到期会 kill 并 wait 回收自己的工作子进程；
Ctrl+C 也停止它，不终止服务或用户其他进程。离线测试实际启动阻塞子进程并验证此路径。
这不是精确实时 SLA：操作系统创建进程/调度/回收仍可能延迟；被强杀的本地 baseline 可能
不完整，不能当作证据。不要直接调用内部 `--worker` 绕过监督。

### 本地只读命令（镜像内真实本地读取已验证，重启仍未验证）

在仓库根目录，确认本地已有正确集合后运行。before 保存摘要，after 用新连接比较；
如只连续运行这两条，**只证明两次读取一致，不证明重启持久化**。

```bash
CHROMA_HOST=127.0.0.1 CHROMA_PORT=8001 CHROMA_SSL=false uv run python scripts/check_chroma_persistence.py --help
CHROMA_HOST=127.0.0.1 CHROMA_PORT=8001 CHROMA_SSL=false uv run python scripts/check_chroma_persistence.py before --baseline .p19-private/chroma-before.json --context local-p19-existing-volume
CHROMA_HOST=127.0.0.1 CHROMA_PORT=8001 CHROMA_SSL=false uv run python scripts/check_chroma_persistence.py after --baseline .p19-private/chroma-before.json --context local-p19-existing-volume
```

此前发布前补验在本地重建的生产镜像 `travel-planner:p19-local` 内实际执行 help/before/after，读取现有
77 条、384 维集合并直接 query。容器 UID 10001、内存限制 2 GiB；没有 API 启动/第二模型加载。
容器使用 `chroma:8000`，基线与上面宿主机 `127.0.0.1:8001` 不可混用。已安全复制到本机
`.p19-private/chroma-image-local-before-20260915.json`；两次读取间没有重启 Chroma。

### 生产执行位置与步骤（NOT VERIFIED；本轮不执行）

发布完成报告不包含生产 before/after 摘要、Chroma-only 重启与排除自动重建的记录。
`/ready` 成功、API 重启恢复计划或本地 77 条记录比较都不能替代这条证据链。

前提：用户批准维护窗口，P19 后端已部署且健康，现有索引已稳定。记录 API deployment ID、
Chroma service/volume 的非敏感标识、时间；确认不会同时发布或运行 indexer。
使用授权的现有 API 容器私网，不开放 Chroma 公网，不把本地 `railway run` 当作私网隧道。

1. 在自己的终端按实际 ID 连接（尖括号是占位符）：

   ```bash
   railway ssh --project <PROJECT_ID> --service <API_SERVICE_ID> --environment <ENVIRONMENT_ID> --deployment-instance <API_INSTANCE_ID>
   ```

   该方式进入已部署容器，见 [Railway SSH 文档](https://docs.railway.com/cli/ssh)。
   权限/模块缺失则停止，不自行注册新 SSH 密钥或修改云配置。
2. **在容器内**执行下列命令。`/app/data/generated` 已由现有 Dockerfile 赋予运行用户写权限；
   `/app` 本身不可写。`umask` 限制新摘要文件的权限，`PYTHONPATH` 只用于寻找已部署代码。

   ```bash
   cd /app/data/generated
   umask 077
   PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence --help
   PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence before --baseline .p19-private/chroma-before.json --context p19-production-existing-chroma-volume
   ```

3. before 成功后，**停下来由用户明确批准并仅重启 Chroma**。保留其 volume，不重启 API，
   不重新部署或触发 bootstrap/indexer，不删除任何数据。此文档不是本轮重启授权。
4. Chroma 恢复后在同一 API instance、同一目录执行：

   ```bash
   PYTHONPATH=/app /app/.venv/bin/python -m app.deployment.chroma_evidence after --baseline .p19-private/chroma-before.json --context p19-production-existing-chroma-volume
   ```

5. 期望 data comparison PASS，且 count、IDs、metadata、内容抽样、向量 anchor 一致。**还须**
   用户提供 Chroma-only 重启时间与 API instance 未变、期间没有 bootstrap/upsert 的证据；
   否则工具会继续显示 `NOT VERIFIED restart`，不能宣称 volume 验收通过。

快照传出：before 成功后，在**本机**仓库目录用已经注册、获准使用的 SSH 身份执行：

```bash
umask 077
mkdir -p .p19-private
scp <API_SERVICE_INSTANCE_ID>@ssh.railway.com:/app/data/generated/.p19-private/chroma-before.json .p19-private/chroma-production-before.json
git check-ignore .p19-private/chroma-production-before.json
```

`API_SERVICE_INSTANCE_ID` 是控制台 Copy Service Instance ID，不是 Service ID；不要把占位符
原样执行。采用 [Railway 官方 SSH/SFTP 支持](https://docs.railway.com/cli/ssh)，仅传出这个摘要
文件，不打包 logs/env/认证状态，不上传 Git/公共存储。目标文件已存在时先停止选新文件名，
不要覆盖此前证据。没有 SSH 权限就停止请用户安排，不自行注册密钥或修改云变量。
API 根文件系统可能随部署替换而消失；本地保管副本不能替代“API instance 未变”的独立证据。

停止条件：集合不存在/空、配置或摘要不一致、超时、API 曾重启、无法排除自动重建、基线丢失。
不要“修复后重跑直到通过”。不要展示完整环境、索引记录或原始日志。基线丢失需重新约定
验收窗口，不能事后补造。生产容器内工具执行仍无独立记录；此前只重建并验证了本地生产镜像。
用户已报告 P19 发布完成，但这不单独证明当前运行镜像的内容。补验时先核对实际 API revision
和 help；本机存在 scripts 文件不意味着当前云镜像一定可运行这个模块。

## 5. 安全、发布与维护

真实 `.env`、认证状态、HAR、trace、测试输出、模型缓存、生成索引不进入 Git。只有三张
人工逐张检查的 fixture JPG 可分享。Auth0 SDK 中的 PEM 格式分隔符不是完整私钥；应结合
实际 bundle/module graph 和合成凭据来源检查，不以改成字符串拼接或单次正则结果宣称安全。
扫描不是全历史审计，也不能证明所有格式的秘密都不存在。

历史 Qwen key、Duffel token、LiteAPI key：**USER CONFIRMED revoked — 2026-09-15**。
用户明确确认三家旧凭据均已撤销，Railway 与本地使用替换后的凭据。只记录确认状态和日期，
不是代理访问控制台的独立验证；不记录值/片段，本轮不轮换密钥、不改生产 variables。

### 发布记录与后续兼容性维护

功能已提交为 `73e9933` — `fix: clarify itinerary quality and finalize acceptance checks`。
用户以“好了都搞定了，现在更新 md 吧”报告发布完成；前后端发布记为整体层面的
**USER-REPORTED COMPLETE**，不补造各平台 deployment ID、时间、SHA 或逐步操作证据。
GitHub hosted CI 的已记录通过结果仍是 P18 历史；新的 P19 run 尚无独立记录。
Railway 自动部署是否恢复开启、Wait for CI 当前状态未查询，不能擅自记为已开启。

本次交接采用的兼容顺序为 **新前端 → 旧标签页刷新/关闭 → 新后端**：

1. 新前端接受旧后端缺少 quality/warnings 的响应，显示 unknown/historical 警告。
2. 旧严格 Zod 前端会拒绝新字段；发布窗口需提醒用户刷新并核对版本。整体发布完成
   不证明每个旧标签页已刷新，不能强制所有已打开浏览器自动更新或承诺零中断。
3. 新前端 + 新后端的 accepted、forced-finalized、error、恢复有本地证据；不能将这些
   fixture/PostgreSQL 结果直接改名为真实双用户生产验收。
4. 后续兼容性发布保留这个顺序；必要时短维护窗口。回滚先后端并保留兼容的新前端，
   不先把前端退回无法识别新字段的版本。保留数据库、volume、认证及限流边界。

“optional 字段”不意味着任意旧严格客户端都兼容；本轮没有放宽 Zod 成任意透传。
后端 SDK 中若存在用户自建的严格消费者，也须先升级消费者再升级响应生产者。

此前本地 Node 实验直接加载 `git show 6bc79ba:frontend/src/api/schemas.ts` 的旧 Zod，与 P19
schema 解析同一合成 payload。旧 schema 对 legacy plan 成功，对含 quality/warnings 的
accepted 与 forced-finalized plan/SSE 都报 unrecognized_keys；当前 schema 接受三种形状。
发布前补验的 5 项质量 UI 测试通过；新后端数据库重开和更早的 fixture E2E 提供新/新恢复证据。
准确兼容矩阵见验收报告；不以“字段 optional”推断旧客户端兼容，也不等于真实云端验收。

后续为维护与可选改进：成本/内存、后续数据源、用户反馈、补充尚缺的云证据和可选视频。
视频未录制，不阻塞代码实现或用户报告的发布完成；凭据撤销已有用户确认，不自动进入 P20。
保持既有模型/语料/维度、五路结构和供应商边界。
历史本地 1 GiB fresh-index OOM 与 2 GiB 验证是 P18 记录，
不是 P19 新测试，也不是 Railway 实测内存结论。前端大 chunk 提示仍待将来单独评估。
