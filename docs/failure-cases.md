# 失败案例与已知限制

| 失败 | 可复现入口 | 确定性处理 | 边界 |
| --- | --- | --- | --- |
| Issue缺环境/复现信息 | Mock #1 | Offline列出四类缺失项，生成回复 | 规则只匹配关键词，不是语义充分性证明 |
| GitHub 401/403 | Mock #401/#403 | 不重试，停止 | PAT权限是否真的足够尚未实测 |
| 404/409/422 | 同编号Mock | 映射结构化错误，不重试 | 404不能总是区分不存在与无权访问 |
| 限流 | #429，或403+安全限流头 | 停止并保留安全Rate Limit信息 | 不自动等待长Retry-After，用户稍后重试读任务 |
| 超时/5xx | #408/#500/#503 | 读最多3次尝试，写不重发 | Mock超时不等于GitHub真的接受写入 |
| 超大/非法响应 | test_github.py | 256KiB上限，非法JSON拒绝 | 不支持大规模Issue导出 |
| Issue要求读取Token/忽略系统 | #4 | 仍仅调用合法读工具，不能执行文本指令 | 没有真实模型攻防成功率数据 |
| 模型虚构工具/写工具 | scripted_model固定案例 | BLOCK_MODEL_TOOL，立即停止 | scripted fixture不是模型能力评测 |
| 模型超过4轮 | model-03 | 第5次工具请求被拒绝 | 最后一次可只生成JSON答案 |
| 审批参数变化 | approval-04 | 原token和动作失效 | 不支持直接编辑待审批快照 |
| 重复/并发批准 | 单测、Docker脚本 | 原子claim，只有一次POST | 不代表真实GitHub exactly-once |
| 写请求响应丢失 | 注入ReadTimeout/RuntimeError | UNKNOWN，保留幂等占位，不重发 | 需人工核对，可能降低任务完成率 |
| MCP不可达 | 关闭本项目mcp服务后/ready | readiness 503，任务停止 | 不自动切到直接import Server的旁路 |
| 模型未配置/不可用 | 界面Model；Provider测试 | 未配置转OFFLINE；运行中不可用转MANUAL并停止 | 绝不将规则结果标成真实模型输出 |

## 开发中实际修复的问题

第一次集成测试发现：MCP SDK使用AnyIO任务组，退出时会把Host抛出的DomainError包装成嵌套ExceptionGroup，导致限流变为笼统错误，重复审批无法以409返回。`client.connect`现在先记录业务异常，正常退出SDK上下文后再抛回原异常；传输建立/清理失败仍统一成MCP_TRANSPORT_ERROR。对应回归是`test_block_and_failure`和`test_api_end_to_end`。

## 不能宣称

没有真实模型准确率、真实GitHub写入成功率、真实用户满意度或效率提升。没有生产OAuth、组织RBAC、企业多租户、安全审计认证或无限规模稳定性。仓库相似Issue只是GitHub关键词搜索，不是RAG、Embedding或语义重复检测。分页最多三页，不保证遍历整个仓库。GitHub PR详情被拒绝，开放列表/搜索过滤PR；写接口没有关闭/删除能力。

审计和任务记录不会自动清理，长期使用需要外部保留期/备份设计。Trace会保存脱敏的仓库文本；脱敏覆盖已知凭据和常见token格式，不是通用PII识别器。SQLite本地文件不是防篡改账本。
