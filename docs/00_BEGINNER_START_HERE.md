# 从零开始：你实际要做什么

## 先理解这件事

这个项目不是“复制一段代码然后运行”这么简单。它由多个系统组成：

1. Python 后端。
2. FastAPI HTTP 接口。
3. LangGraph 多 Agent 工作流。
4. Qwen 或其他兼容模型。
5. PostgreSQL 状态与长期记忆。
6. Redis 缓存。
7. ChromaDB 向量检索。
8. FastMCP 工具服务。
9. SSE 流式输出。
10. 日志、Tracing 和监控。
11. 测试、容器和部署。

作为新手，正确做法是**逐层搭建、每层验证**，而不是让 Codex 一次生成几万行代码。

## 推荐工具

以 macOS 为例：

- Codex 桌面应用或 Codex IDE 扩展。
- VS Code。
- Git。
- Python 3.11 或 3.12。
- `uv` 作为 Python 环境和依赖管理器。
- Docker Desktop。
- 一个 Qwen 兼容 API Key，后期再配置。
- 可选：LangSmith API Key，最后再配置。

## 最关键的操作原则

每完成一个阶段，都必须看到：

1. Codex 说明改了什么。
2. 终端命令成功。
3. 测试通过。
4. 你能在浏览器或命令行看到预期结果。
5. Git 保存一个可回退的版本。

只要某阶段失败，就不要进入下一阶段。

## Codex 使用方式

Codex 可以在本地项目文件夹里读取代码、运行命令、写测试和修改文件。最接近“把这个项目直接导过去”的方式是：

1. 解压本包。
2. 在 Codex 中打开整个文件夹。
3. 让 Codex先读 `AGENTS.md`。
4. 按编号依次粘贴 `docs/prompts` 中的提示词。
5. 每一阶段只做一件事。

## 第一天的目标

第一天不要碰多 Agent、RAG 或 MCP。

只完成：

- 安装工具。
- 打开项目。
- 启动 PostgreSQL、Redis、Chroma。
- 启动 FastAPI。
- 浏览器访问 `/health`。
- 运行测试。
- 做第一次 Git commit。

能完成这些，你就已经建立了一个可靠的开发基线。
