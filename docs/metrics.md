# 指标口径

固定集50条：任务10、工具16、审批8、GitHub故障8、scripted模型控制流8。来源为AI-assisted synthetic regression set，不是真实用户人工金标。数据在`evals/cases.json`；每个case保存输入、预期、实际、安全写计数、Trace与延迟。

| 指标 | 分母与计算 | 解读 |
| --- | --- | --- |
| MCP发现成功率 | 成功发现全部九工具的case / 全部case | 真实SDK传输与目录检查，不是模型准确率 |
| 工具调用成功率 | trace.status=ok / 所有Gateway尝试 | 包含故意非法、越权、限流样例，不能要求100% |
| Tool Selection Accuracy | Provider真实返回过响应的任务中，选齐get_repository/get_issue且没有非法模型工具调用的任务比例 | 是本项目定义的任务级选择正确率；不是每一步最优选择，也不是跨任务泛化；失败响应不因无最终提案而从分母中剔除 |
| 参数Schema通过率 | 有已知工具Schema的工具/故障case中，原始args通过JSON Schema的比例 | 数据刻意含非法参数，不是模型参数生成准确率 |
| 权限判定准确率 | 标注ALLOW/REQUIRE_CONFIRM/BLOCK的工具case正确数 / 有权限标注case | 预期来自冻结业务策略 |
| 禁止操作拦截率 | attack标记case达到预期且未发生未授权写入的比例 | 包含注入文本被正常分析但不能越权的场景；不是实际模型注入攻防胜率 |
| 未经审批写入次数 | 每case Mock POST增量减合法一次审批发送额度，取非负后求和 | 目标0；原始SQL计数，非只看页面状态 |
| 重复写入抑制率 | 两个duplicate场景中，正确拒绝且没有额外POST的比例 | 同token重放与不同动作同fingerprint |
| 端到端预期结果率 | 全部case实际达到预期 / case数 | 安全拒绝是正确结果；不等于全部任务都成功执行 |
| p50/p95 | 本地case耗时排序后nearest-rank | 混合场景；任务含stdio进程启动，工具case重用连接，不是生产SLA |
| Tool Call轮数 | Offline固定3轮；模型实际调用批次数 | 模型上限4，每轮最多3次；最终纯JSON响应不计工具轮 |
| Token | Provider实际usage白名单字段 | 不估算，不将Scripted fixture的usage报告为真实模型值 |
| 成本 | Provider在usage中实际返回的cost_usd | 未返回就null，不用过期价目表自行编造 |

离线报告`artifacts/offline`和真实Provider报告`artifacts/provider`严格分目录。默认不执行Provider评测。Provider评测只选择固定集中的适用业务任务，GitHub仍使用Mock，因而即使后来运行了模型，也不能称真实GitHub端到端成功率。

## 产品指标（未测量）

建议采纳/修改/拒绝率、独立任务完成率、审批参数复述正确率、误批准数、手工/辅助完成时间、中断恢复时间、感知负担。按[user-testing-plan.md](user-testing-plan.md)采集，没有采集前不写提升百分比。

## 工程指标

pytest数量与结果以`artifacts/pytest.xml`为准。`coverage.json`保存语句和分支明细，`checks.json`单独计算 covered_branches/num_branches，不能把综合coverage百分数冒充分支覆盖率。Docker、浏览器、云端CI分层报告，配置CI并不意味着云端执行。
