# 竞品与替代方案

调研快照：2026-09-07。比较的是架构和适用范围，不是经过控制实验的性能排名。官方来源和版本证据见[复用决策](reuse-decisions.md)及[快照](../artifacts/research-snapshot.json)。

| 替代方案 | 强项 | 对学生团队场景的差异 | 本项目选择 |
| --- | --- | --- | --- |
| [GitHub Issue Forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms) | 结构化收集新Issue字段、成本低 | 不能直接代替已有自由文本Issue的上下文分析 | 应作为互补基线，不宣称Agent普遍更好 |
| 手工GitHub网页操作 | 最少部署、完整控制 | 重复查上下文与回复需要人工 | 用户测试中的对照工作流 |
| [官方GitHub MCP Server](https://github.com/github/github-mcp-server) | 大量工具、正式GitHub生态、可组合 | 功能面远超本项目；Host仍需逐动作审批策略 | 不Fork，独立只实现九个工具 |
| [Python SDK + Inspector](https://github.com/modelcontextprotocol/python-sdk) | 协议能力和调试基础 | 不是Issue工作流、审批数据库或产品界面 | SDK直接依赖，官方Client作为自动验证器 |
| [LangChain MCP Adapters](https://github.com/langchain-ai/langchain-mcp-adapters) | 适合已有LangChain应用接MCP | 本项目会增加无必要编排依赖 | 只参考Schema转换设计 |

差异化不是“更强的GitHub Agent”，而是范围小、凭据所有权清晰、完整可见审批快照、持久化幂等和可复现离线验证。九工具的覆盖不足、规则基线粗糙、真实模型效果未知都是已知劣势。

在只有新Issue字段收集需求时优先Issue Forms；在处理已有非结构化文本、动态上下文与多种协作意图时，才值得验证这个Agent是否节省认知工作。
