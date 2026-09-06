# 代码学习地图

围绕一次任务阅读，而不是先背框架术语。

| 文件 | 核心入口 | 要能解释的问题 |
| --- | --- | --- |
| src/issue_agent/api.py | create_app、task、decide | cookie/CSRF如何保护审批？为什么先发现MCP再发token？ |
| src/issue_agent/models.py | TaskRequest、TriageProposal、ApprovalProof | 用户Issue字符串为何可接受，而工具参数整数拒绝字符串？ |
| src/issue_agent/agent.py | run_task、model_loop、persist_proposals | 四轮如何计数？怎样明确区分offline和模型结果？ |
| src/issue_agent/client.py | connect、MCPGateway.discover/call/model_tools | Schema来自哪里？为什么不能把Server函数直接import到演示路径？ |
| src/issue_agent/server.py | build_server、ToolService.call | 装饰器如何注册九工具？Server为何重复验证Host已验证的参数？ |
| src/issue_agent/security.py | Policy、parse_issue、fingerprint、redact | Allowlist、URL拒绝和参数哈希分别解决什么？ |
| src/issue_agent/storage.py | pending、decide、claim、finish | 怎样防并发重放？为什么网络请求不在SQL事务里？ |
| src/issue_agent/github.py | execute、request | 401/429/5xx处理为何不同？哪些请求能重试？ |
| src/issue_agent/mock_github.py | MockGitHub | 离线HTTP夹具如何和真实Adapter走相同路径？ |
| src/issue_agent/provider.py | CompatibleProvider.complete | 动态tools怎样送到模型？usage从哪里来？ |
| src/issue_agent/evaluation.py | evaluate_case、summarize | 50/50究竟测的是什么，不测什么？ |
| src/issue_agent/static/ | app.js、index.html、style.css | 完整参数展示、状态、textContent/CSP如何协同？ |
| tests/ | security/storage、github、agent/mcp、api、http、evaluation | 每个保证对应哪项可失败的测试？ |
| scripts/ | verify、mcp_smoke、docker_verify、ui_verify | 如何证明配置真的运行过？ |

先按`api.task -> run_task -> connect -> gateway.call -> MCPServer工具 -> ToolService -> Adapter`走读取路径，再按`api.decide -> Store.decide -> MCP写调用 -> Store.claim -> Adapter -> finish`走写路径。

有价值的调试练习：把工具issue_number换成字符串；注入虚构工具；将approval正文改一个字符；让Mock写请求抛ReadTimeout；并发重放同一个proof；重启MCP后读取PENDING/SUCCEEDED。每次先预测SQL状态和POST次数，再看实际证据。

冻结后的修改建议以单个约束为单位，例如增加一种缺失字段、降低page上限、新增一个安全回归。新增写能力前必须同时更新Policy、Schema、审批展示、最小GitHub权限和测试，不只加一个工具函数。
