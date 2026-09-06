# 一次请求的完整流程

以 Issue 1 的“检查缺失信息，并生成评论提案”为例：

1. 浏览器 GET `/api/session`，得到随机会话 cookie 和 CSRF。数据库只保存会话 cookie 的 SHA-256。cookie HttpOnly/SameSite Strict，审批 POST 还验证 Origin 和 CSRF。
2. POST `/api/tasks` 经 Pydantic 严格检查外层任务。不合法参数返回 422，不回显原始敏感值。URL 输入只解析 github.com 的指定仓库 Issue 路径，从不抓取该 URL。
3. `run_task` 再做仓库授权，并生成 run_id。真实 Provider 缺配置时明确降级为 offline；运行中 Provider 不可用则停止，进入 manual 状态，不能把失败模型结果换成伪成功。
4. `connect` 使用官方 SDK Client 连接独立 stdio 进程或 Docker MCP HTTP。发现工具与 JSON Schema，检查完整目录恰为九个工具。新版走 `server/discover`，旧初始化仅在兼容测试中使用。
5. Offline 是固定三轮，每轮两次 MCP 读取：仓库/Issue、标签/评论、相关搜索/开放 Issue。模型模式由模型选择六个只读工具，每批最多三次、最多四个工具调用轮次；最后可额外请求一次不提供工具的结构化答案。
6. Client 校验工具名、参数、任务仓库/Issue范围。Server 再次严格校验和授权。任何工具异常即停止。模型批次会先整体校验，避免部分批次执行后才发现剩余参数非法。
7. GitHub Adapter 构造固定 API 路径，顺序请求。一个任务最多 24 次 HTTP 尝试，包括读重试；单次超时 10 秒，响应上限 256 KiB。每页最多 30 条，page 1-3，不跟随第三方 Link URL 或重定向。
8. 工具结果带 `untrusted`，模型上下文另包 `untrusted_data`。Issue 文本不被解析为策略、环境变量名或批准证明。模型输出以 `TriageProposal` 校验，并再次校验 ActionDraft 的仓库与 Issue 范围。
9. 未允许写提案就直接返回。允许写提案时，存完整规范化参数、工具名、session、SHA-256、影响、短期有效期。此时没有 GitHub POST。
10. 用户检查整份快照，POST `/api/actions/{id}/approve`，带所见 fingerprint。Web 检查当前会话和快照，再把 PENDING 原子改为 APPROVED，并生成随机一次性 token，数据库只留 hash。
11. Web 经 MCP 调用写工具，附 approval proof。Server 把 session/tool/参数指纹/token/有效期逐项核对，在 `BEGIN IMMEDIATE` 中检查唯一 execution fingerprint、占位并消费 token，提交事务后才发送一次 POST。
12. 成功记录 SUCCEEDED；已知拒绝记录 FAILED；发送后超时/5xx/未知异常记录 UNKNOWN。结果与安全 Trace 存审计。重复审批返回 409，重复工具执行不会再向 GitHub 发送写请求。

拒绝走 PENDING -> REJECTED 并审计，没有写 MCP 调用。EXPIRED、INVALIDATED、DUPLICATE、UNKNOWN 都不会自动重发。原始分析快照与后续审批状态是两类对象，查看动作最新状态不能只看初始 TaskResult。
