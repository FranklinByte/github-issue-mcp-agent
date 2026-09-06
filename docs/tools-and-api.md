# 工具、Schema 与 API

## MCP 工具

| 工具 | 业务参数 | 权限 | GitHub REST |
| --- | --- | --- | --- |
| get_repository | repo | ALLOW | GET /repos/{repo} |
| get_issue | repo, issue_number | ALLOW | GET /repos/{repo}/issues/{n} |
| list_open_issues | repo, page, per_page | ALLOW | GET /repos/{repo}/issues?state=open |
| search_issues | repo, query, page, per_page | ALLOW | GET /search/issues，强制 repo/is:issue |
| list_labels | repo, page, per_page | ALLOW | GET /repos/{repo}/labels |
| get_issue_comments | repo, issue_number, page, per_page | ALLOW | GET /repos/{repo}/issues/{n}/comments |
| add_labels | repo, issue_number, labels | REQUIRE_CONFIRM | POST /repos/{repo}/issues/{n}/labels |
| post_comment | repo, issue_number, body | REQUIRE_CONFIRM | POST /repos/{repo}/issues/{n}/comments |
| create_issue | repo, title, body | REQUIRE_CONFIRM | POST /repos/{repo}/issues |

完整生成 Schema 在 [mcp-smoke.json](../artifacts/mcp-smoke.json) 的 tools 数组；来源是 SDK `@server.tool` + Pydantic 类型，不是手写 HTTP 接口。

实际 MCP 参数 envelope：

```json
{"args":{"repo":"student-lab/course-project","issue_number":1},"run_id":"task-123"}
```

写工具还接受 `authorization`，含 action_id、session_id、token；此对象只在可信 Web 与 Server 间传递，不传给模型，不落明文日志。模型工具 Schema 由发现结果中 `args` 的定义动态提取，隐藏 run_id 和全部写工具。

`extra=forbid`；Issue 是严格正整数，字符串 `"1"` 不等于工具参数 integer。repo 仅 owner/repo，大小写规范化。page 1-3，每页1-30，标签1-5个，标题1-200字符，正文1-6000字符。query 只允许文字、空白、点、连字符，禁止冒号和斜杠等 GitHub 搜索限定符。

业务拒绝返回结构化 `{ok:false,error,permission,uncertain}`；框架 schema 错误可为 MCP `is_error`。Client 检查两层，不能把协议 HTTP 200 等同工具成功。

## Web API

交互式 API 文档：`/docs`。浏览器业务请求必须先建立 session。所有写 API 带 `X-CSRF-Token`，本地演示不实现生产身份认证。

| 路径 | 方法 | 结果 |
| --- | --- | --- |
| /health | GET | Web 存活 |
| /ready | GET | SQLite 与真实 MCP 工具发现均可用 |
| /api/session | GET | 会话、CSRF、仓库列表、GitHub模式、transport |
| /api/tasks | POST | TaskRequest -> TaskResult |
| /api/runs/{run_id} | GET | 当前会话的历史分析快照 |
| /api/proposals | POST | 用户手动 ActionDraft -> PendingAction |
| /api/actions | GET | 当前会话最新动作列表，最多50条 |
| /api/actions/{id}/approve | POST | 校验 fingerprint，审批后经 MCP 执行 |
| /api/actions/{id}/reject | POST | 拒绝并审计，不执行写工具 |
| /api/audit | GET | 当前会话最近100条审计事件 |

请求例子：

```json
{"repo":"student-lab/course-project","issue":1,"task":"检查缺失信息，建议标签和回复","allow_writes":true,"mode":"offline"}
```

Web 校验错误422、会话/CSRF/Origin/越权403、已决定/失效动作409、请求超长413。任务中的工具/模型错误通常以 TaskResult.status=stopped 返回，而不是冒充 HTTP 层故障。
