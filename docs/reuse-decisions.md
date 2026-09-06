# 开源调研与复用决策

核查日期：2026-09-07。来源是官方仓库 README、LICENSE、发布页、GitHub REST 元数据、PyPI 和官方协议文档。未 Fork、改名或复制任何完整服务。下表是调研时快照，不是持续更新的版本承诺。

原始版本、维护时间、树SHA、许可证元数据与测试路径样本保存在 [research-snapshot.json](../artifacts/research-snapshot.json)，由 `scripts/research_snapshot.py` 只读获取。该脚本不运行上游测试，不把上游测试存在等同于本项目已验证。

| 候选 | 维护快照 | 许可证核查 | 架构、测试与边界 | 决策 |
| --- | --- | --- | --- | --- |
| [Python SDK](https://github.com/modelcontextprotocol/python-sdk) | push 09-06；GitHub release v2.0.1；PyPI 最新稳定 2.1.1 | MIT | 官方 MCPServer / Client、类型生成 Schema；stdio / Streamable HTTP；pytest 协议交互测试。SDK 不替应用做仓库权限与审批 | 直接依赖 PyPI mcp==2.1.1，并在本地核查实际 API 和协议版本 |
| [GitHub MCP Server](https://github.com/github/github-mcp-server) | push 09-05；v1.12.0，09-03 | MIT | Go；工具集、只读模式、PAT 与远程 OAuth；stdio / HTTP；Go 单测。范围远大于本项目，工具选择不等同于逐动作用户授权 | 仅参考最小权限与工具分组，不依赖、不复制、不 Fork |
| [Inspector](https://github.com/modelcontextprotocol/inspector) | push 09-06；2.5.0，09-02 | 当前根目录没有 LICENSE，REST license endpoint 404；不能凭旧资料声称整个当前版本 MIT | 独立客户端、工具列表与调用调试；CLI/UI；transport 诊断。不是生产鉴权层 | 使用等价官方 Python Client 做可复现发现/调用验证，不打包 Inspector；保留手动使用入口 |
| [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters) | push 09-01；0.3.2，08-06 | MIT | MCP 工具转 LangChain Tool；会话/传输适配，pytest；审批仍是 Host 责任 | 不引入 LangChain/LangGraph，借鉴动态 Schema 转换思路 |
| [reference servers](https://github.com/modelcontextprotocol/servers) | push 09-03；2026.8.31 | LICENSE 声明 MIT 向 Apache-2.0 迁移，文档 CC-BY-4.0；不是统一 MIT | 多种参考 Server、工具注册与测试示例；不保证业务生产安全；GitHub 旧实现不作为新项目基础 | 只阅读架构，不复制实现或捆绑包 |

## 协议版本的重要变化

[最新正式规范](https://modelcontextprotocol.io/specification/2026-07-28)和[发布说明](https://blog.modelcontextprotocol.io/posts/2026-07-28/)已将协议核心改为无状态，请求携带版本和能力，使用 `server/discover`。旧 `initialize/initialized` 属于向后兼容路径。项目主路径使用 2026-07-28，另以 SDK legacy 模式验证 2025-11-25 握手，不能宣称新版仍强制旧握手。

[SDK v2 迁移说明](https://py.sdk.modelcontextprotocol.io/migration/)确认 `FastMCP` 改为 `MCPServer`、Python 字段 snake_case、SDK HTTP 栈使用 httpx2。GitHub 和模型 Adapter 独立依赖 httpx，两种客户端对象不混用。正式版本全部由 uv.lock 冻结。

## 本项目自己的实现

独立实现九个业务工具、严格参数校验、仓库 Allowlist、SQLite 审批状态机、幂等占位、受限 REST Adapter、离线 MockTransport、轻量循环和工作台。MCP 负责发现/调用协议，权限和可靠性由确定性代码负责；工具 annotation 和 Prompt 均不是授权依据。

写操作不盲目重试：GitHub 不提供本项目所需的通用幂等键。一次持久化 claim 后至多发出一次写请求；超时/崩溃造成的不确定结果进入 UNKNOWN 或保留 EXECUTING，不自动恢复重发。牺牲自动可用性以避免重复副作用。

## API 与权限依据

- [GitHub REST 最佳实践](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)：顺序请求、分页、限流和有限重试。
- [Issues REST](https://docs.github.com/en/rest/issues/issues)、[labels](https://docs.github.com/en/rest/issues/labels)、[comments](https://docs.github.com/en/rest/issues/comments)：Fine-grained PAT 针对选定仓库，Metadata read，Issues read-only 或 read/write；无 Contents、Administration、Members 权限需求。
- [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling)：模型提出工具调用，应用负责执行与校验。使用兼容 Chat Completions HTTP Adapter，不固定一个未经验证可用的模型名。

## 集成风险

新 SDK 2.x 与旧示例有破坏性差异，靠锁文件、stdio/HTTP/legacy 三类测试冻结行为。Docker HTTP 仅内部网络，不实现标准远程 OAuth，明确为本地演示传输。审批 API 属于本项目应用协议，不冒充 MCP 标准授权。当前没有真实 Provider、真实 GitHub 写入或真实用户研究证据。
