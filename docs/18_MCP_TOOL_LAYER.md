# P11 — MCP Travel Tool Layer

## 先用一句话理解

P10 解决“从本地知识文档里找哪些段落”，P11 解决“用统一协议调用天气、路线、航班、酒店和景点工具”。MCP（Model Context Protocol）可以理解成工具的统一插座：工具内部仍是普通 Python 函数，但插头的名称、输入 schema、输出 schema 和传输方式有共同规范。

这仍是本地演示。五个工具最终调用 P03 的确定性 mock provider，不访问真实航司、酒店、天气、地图、LLM 或公网 API，也没有测得任何性能提升。

## 组成部分

- 普通 Python 函数只在当前进程内被代码直接调用；MCP Tool 还公开名称、说明、JSON Schema 和协议响应，客户端可以先发现再调用。
- FastMCP 3.4.7 根据 Python 类型标注生成输入和输出 schema，并负责 MCP 协议与 transport。
- MCP Server 是“插座面板”。本阶段有两块彼此独立的面板。
- MCP Client 是“插头管理器”。`MultiServerMCPClient` 同时知道两个 Server，并用 `get_tools()` 将发现结果转换成 LangChain `BaseTool`。
- Tool Registry 用公开的 `tool.name` 建立映射。顺序不重要；缺少、未知或重复名称都会明确失败，绝不偷偷选择第一个同名工具。

两个 Server 的分工：

| Server | Transport | 工具 |
| --- | --- | --- |
| `local_tools` | STDIO | `get_route`, `get_weather` |
| `travel_tools` | Streamable HTTP | `search_attractions`, `search_flights`, `search_hotels` |

## STDIO 是什么

STDIO 使用子进程的标准输入和标准输出传送 MCP 消息。客户端用当前虚拟环境的绝对 `sys.executable` 启动固定模块：

```text
python -m app.mcp_tools.servers.local_stdio
```

因此用户不需要手动常驻启动这个 Server。stdout 必须完全留给协议消息；普通 `print()` 会混入协议并破坏连接。当前模块不打印普通日志，也不读取 `.env` 的密码、Token 或 DSN。

这里采用 adapter 的默认 stateless 行为：每次工具调用创建 session、完成调用、关闭 session。天气和路线查询没有跨调用状态，所以不需要 stateful session，也不会把 subprocess、Client 或 Tool 写入 LangGraph checkpoint。

## Streamable HTTP 是什么

HTTP Server 是独立进程，默认只监听：

```text
http://127.0.0.1:9001/mcp
```

FastMCP 3.4.7 用 `mcp.run(transport="http")` 启动当前推荐的 Streamable HTTP。P11 不实现旧式 SSE。HTTP Server 可同时服务多个本机客户端，但当前没有认证，只适合本地开发；绝对不要直接暴露公网。公网部署前至少需要 TLS、身份认证、授权、网络边界、限流、审计和秘密管理。

启动 HTTP Server：

```bash
uv run python -m app.mcp_tools.servers.travel_http
```

FastMCP 3.4.7 的 CLI 帮助也确认支持等价的显式方式：

```bash
uv run fastmcp run app/mcp_tools/servers/travel_http.py:mcp \
  --transport http --host 127.0.0.1 --port 9001 --path /mcp
```

看到 `http://127.0.0.1:9001/mcp` 后保持该终端运行。端口占用会由底层 Server 明确报 bind 错误。结束时按 Control+C。

## 输入与输出 schema

所有工具只接收一个 `MCPToolRequest`：

```text
task_id
request_fingerprint
requirements
route_origin（路线工具可选）
route_destination（路线工具可选）
```

`MCPTripRequirements` 把日期、Decimal 金额和 Enum 币种显式变成 JSON 字符串；转回领域对象时仍调用原 `TripRequirements.model_validate()`，没有复制业务验证。

所有工具返回同一个 `MCPToolResponse`：

```text
ok
tool_name
task_id
request_fingerprint
data 或 error（二选一）
provider = deterministic_mock
```

错误只含 `error_type`、`safe_message`、`recoverable`，不含 traceback、命令、环境变量、内部路径、Token 或数据库连接串。

FastMCP 的 typed model 返回会同时生成文本 content 和 structured content。用当前 `langchain-mcp-adapters` 0.3.2 真实验证时，`BaseTool.ainvoke()` 返回公开 `ToolMessage`；完整 envelope 位于：

```text
message.artifact["structured_content"]
```

解码器优先读取该 structured content，也严格支持完整 JSON 字符串和当前 adapter 的单 text-block fallback。它只使用公开字段，不用正则从自然语言猜 JSON，不回显无效原始 payload。

## Direct 与 MCP 模式

默认配置是：

```text
TRAVEL_SEARCH_BACKEND_MODE=direct
```

这继续使用 `DeterministicMockSearchBackend`，启动 FastAPI 不依赖 MCP Server。保留 direct 模式可以让初学者离线学习、让普通测试快速稳定运行，也提供兼容性基线。

验收 MCP 模式时使用：

```bash
TRAVEL_SEARCH_BACKEND_MODE=mcp \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

MCP backend 实现同一个 `SearchBackend` Protocol。P08 Search Worker 不知道数据来自 direct 还是 MCP，五路 `Send` 并行、P09 Reviewer、P10 RAG 和 P07 persistence/memory 继续使用原图结构。持久 state 的 `search_backend_mode` 会明确显示 `mcp` 或 `direct`。

MCP 失败不会静默回退到 direct。航班和酒店仍是 critical：不可用时 Agent 返回安全 HTTP 503；景点、天气、路线仍按 P08 的 non-critical 策略保存错误并允许降级。已成功的并行分支不会被伪造或抹掉。

## Timeout、retry 与生命周期

- discovery 默认 deadline 15 秒；单工具默认 deadline 8 秒。
- `MCP_MAX_RETRIES=1` 表示临时 transport/session 错误最多重试一次。
- 输入验证错误、无效 envelope 和确定性 provider 错误不重试。
- 没有随机 jitter，也不宣称这是生产级重试策略。
- `get_tools()` 只在初始化或受限刷新时调用，不会为每个 SearchTask 重新 discovery。
- readiness 使用缓存 discovery，加本机 HTTP socket 探测；失败后的重新 discovery 有一秒冷却，避免每次请求无限启动 STDIO。
- 当前 adapter 的 `MultiServerMCPClient` 没有公开 `aclose()`；stateless discovery 和工具调用各自退出公开 session context，因此不调用任何私有 close 属性。

## 状态与 readiness

安全诊断：

```bash
curl --noproxy '*' --fail-with-body --silent --show-error \
  http://127.0.0.1:8000/api/v1/mcp/status \
  | uv run python -m json.tool
```

它只返回 backend mode、Server transport、ready、工具名、缺失/重复列表和安全错误类型，不返回 PID、完整命令、URL、env、Tool repr 或 Client repr。该 endpoint 也没有认证，只适合本机。

- direct 模式：`/ready` 仍只检查 PostgreSQL、Redis、Chroma。
- mcp 模式：还要求五个工具 discovery 成功、无重复、HTTP 可连接，并保留成功的 STDIO discovery 状态。
- MCP 不可用时 `/ready` 返回 503，但 `/health` 仍返回 200，证明 Web 进程活着。

## Smoke Test

先启动 HTTP Server，再在另一个终端运行：

```bash
uv run python scripts/check_mcp_tools.py
```

脚本使用真实 `MultiServerMCPClient`，发现 2+3 个工具，逐一调用，并把输出验证回现有 Domain Model。每项成功显示 `PASS`；任意失败显示不含秘密的 `FAIL` 并以非零退出码结束。STDIO Server仍由 Client 自动启动和关闭。

显式 integration test：

```bash
RUN_INTEGRATION_TESTS=1 \
uv run pytest tests/integration/test_mcp_integration.py -vv
```

它使用动态端口启动/停止 HTTP subprocess，真实启动 STDIO subprocess，检查五个工具、MCP backend、P08 graph、P09 review、P10 context、HTTP 停止后的失败和 direct 兼容。普通 `uv run pytest -q` 不启动这些进程。

## 如何判断 P11 完成

1. HTTP Server 能启动，smoke 显示两个 Server 和五个 PASS 工具。
2. MCP 模式 `/api/v1/mcp/status` 是 ready，`/ready` 与 `/health` 都是 200。
3. persistent Agent 能完成 Tokyo 请求，同线程 Paris 请求没有旧 Tokyo 搜索结果，review 与记忆仍正常。
4. 停止 HTTP MCP 后 `/ready` 为 503、`/health` 为 200、Agent 安全失败；重启后恢复。
5. direct 模式不依赖 HTTP MCP，所有普通检查通过。
6. 端口 8000/9001 与 MCP 子进程都已清理，Docker named volumes 保留。

官方 API 参考：

- [FastMCP server transports](https://gofastmcp.com/deployment/running-server)
- [FastMCP typed tools and structured output](https://gofastmcp.com/servers/tools)
- [LangChain MCP adapters](https://docs.langchain.com/oss/python/langchain/mcp)
