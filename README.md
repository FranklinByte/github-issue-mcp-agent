# GitHub Issue 协作 Agent

面向学生开发团队的 GitHub Issue 协作 Agent：基于 MCP 的受控工具调用与人工审批系统。

九个范围受限的 GitHub 工具、最多四轮的轻量模型循环、可检查的写操作提案、SQLite 一次性审批和幂等记录。默认完全离线：官方 MCP Client/Server 真正跨进程或容器通信，GitHub 使用持久化 MockTransport；**Offline 规则分析不冒充真实模型 Agent**。

本地冻结版本 `v1.0.0`，版本与验证边界见 [freeze.json](freeze.json)。本项目有独立本地Git历史，没有配置远程仓库或推送。

![工作台](artifacts/ui/desktop.png)

## 一键启动

Windows / PowerShell 7，先启动 Docker Desktop，然后在本项目目录运行：

```powershell
pwsh -NoProfile -File scripts/start.ps1
```

默认地址 **http://127.0.0.1:8021**；脚本发现占用会选择其他端口并打印地址。Linux/macOS 或固定端口：

```sh
docker compose up -d --build --wait
```

只会启动本项目的 `web`、`mcp` 和 `agent-data` 卷。MCP 没有映射宿主端口，后端网络 `internal: true`；默认 Compose 不接收 PAT。停止：`docker compose stop`；不要用 `down -v`，该选项会删除本项目审批、审计和 Mock 数据。

没有 Docker 时，Python 3.12/3.13 + PowerShell 7：

```powershell
pwsh -NoProfile -File scripts/start.ps1 -Local
```

本地模式启动隐藏 Web 进程并打印 PID，Web 为每次任务启动官方 stdio MCP 子进程；只支持 Mock GitHub。不要以为 HTTP 演示服务已经实现远程 OAuth。

## 演示路径

1. 默认仓库 `student-lab/course-project`、Issue `1`，运行只读分析，查看缺失信息、建议标签和六次 MCP 调用。
2. 勾选“生成写操作提案”再次分析。检查完整参数、仓库、影响和 SHA-256 指纹，批准评论、拒绝标签，查看执行结果与审计。
3. 输入 Issue `4` 查看含 Prompt Injection 的不可信文本；它不能读取环境变量、修改 Allowlist 或伪造审批。
4. 输入 `429` 或 `408` 查看 Mock 限流、超时。选择 Model 且没有配置模型时，页面明确标记降级为 OFFLINE。
5. 用“手动创建提案”选择 `create_issue`，或在任务中写“创建后续 Issue”。所有写操作仍逐项审批。

Mock Issue `2` 包含完整基本信息，`3` 是功能需求，`5` 是问题咨询。`401/403/404/409/422/429/500/503/408` 是故障夹具，不能把这些编号规则理解成真实 GitHub 行为。

## 验证与评测

若只运行过Docker、尚无本地`.venv`，先执行`python -m venv .venv`及`.\.venv\Scripts\python -m pip install uv==0.12.10`。下列命令在项目根目录运行。

```powershell
.\.venv\Scripts\uv sync --frozen
.\.venv\Scripts\python scripts/verify.py
.\.venv\Scripts\python scripts/docker_verify.py
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python scripts/ui_verify.py
```

`verify.py` 保存 Ruff、mypy、依赖一致性、pytest、覆盖率、官方 SDK stdio/legacy 验证及 50 条离线评测的原始输出。Docker/browser 命令会对本项目的 Mock 数据产生测试记录，不接触真实 GitHub。

- [验证记录与边界](docs/validation.md)
- [离线 JSON/逐案例结果](artifacts/offline/results.json)、[CSV](artifacts/offline/results.csv)、[Markdown 报告](artifacts/offline/report.md)
- [Docker 实测](artifacts/docker/verification.json)、[浏览器实测](artifacts/ui/verification.json)
- [官方 SDK 工具与 Schema 证据](artifacts/mcp-smoke.json)

50 条数据标注为 **AI-assisted synthetic regression set**。预期拒绝算安全回归通过，但不算工具执行成功；不能把 50/50 写成真实模型 Tool Selection Accuracy。Provider 专属评测入口：`python -m issue_agent.evaluation --mode provider`，结果单独写到 `artifacts/provider/`；配置方法见下方文档。没有实际模型响应时不输出模型准确率、Token 或成本。

## 技术与边界

Python 3.12、官方 `mcp==2.1.1`、协议 `2026-07-28`、FastAPI、Pydantic、httpx、SQLite。另验证 `2025-11-25` 的 legacy 初始化握手。依赖及哈希锁在 `uv.lock`，Docker 基础镜像固定 digest。

不含 RAG、向量数据库、LangGraph、多 Agent、代码生成、代码审查、Issue 关闭/删除、仓库配置或成员权限修改。真实 GitHub REST Adapter 已实现，**本次没有运行真实模型、没有对业务仓库调用真实 GitHub、没有执行真实写入、没有云端 CI 或用户访谈结果**。开源调研访问官方仓库元数据，不属于业务集成验证。

写入采用 durable claim + 至多一次发送。GitHub 没有通用幂等键，网络丢失响应或进程崩溃后保留 UNKNOWN/EXECUTING，人工核对，绝不声称跨网络绝对 exactly-once。

## 文档导航

| 内容 | 文档 |
| --- | --- |
| 架构、请求流程 | [architecture.md](docs/architecture.md)、[request-flow.md](docs/request-flow.md) |
| 工具 Schema、API、PAT/模型配置 | [tools-and-api.md](docs/tools-and-api.md)、[configuration.md](docs/configuration.md) |
| 权限、安全与失败 | [permission-design.md](docs/permission-design.md)、[failure-cases.md](docs/failure-cases.md) |
| 产品定位与竞品 | [prd.md](docs/prd.md)、[competitive-analysis.md](docs/competitive-analysis.md) |
| 用户与验证计划 | [user-personas-and-workflows.md](docs/user-personas-and-workflows.md)、[user-testing-plan.md](docs/user-testing-plan.md) |
| 指标 | [metrics.md](docs/metrics.md) |
| 学习、介绍、简历、面试 | [code-map.md](docs/code-map.md)、[portfolio.md](docs/portfolio.md)、[interview.md](docs/interview.md) |
| 开源复用 | [reuse-decisions.md](docs/reuse-decisions.md)、[THIRD_PARTY.md](THIRD_PARTY.md) |

项目是 AI 辅助构建的个人实现。学习和面试前应能解释每个安全检查及失败边界；不将官方 MCP SDK、合成样本或未执行的集成验证包装成个人原创或生产数据。
