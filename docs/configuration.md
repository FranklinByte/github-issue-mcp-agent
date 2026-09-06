# 配置和真实集成边界

默认不需要账号或 Key。环境变量不会自动从 `.env.example` 加载。本地进程使用自己的环境；Compose 仅使用 YAML 中明确列出的变量。

## 模型

Web 进程设置 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY`，然后在界面选 Model。使用 Chat Completions 兼容 `/chat/completions`，支持 tools、tool_choice、JSON object response 和 usage。没有固定默认模型名，避免假设某账号可以访问某模型。Provider 设置来源只能是操作者环境，不接受 Issue 指定的 URL。

密钥通过本地安全环境配置，不写入仓库，不粘贴到聊天。运行 `python -m issue_agent.evaluation --mode provider` 前需要明确接受该 Provider 的费用和仓库文本外发。该评测只访问本地 Mock GitHub，但会向配置的模型发送合成 Issue 数据。

HTTP 超时30秒，不自动重试模型请求，响应上限256KiB。模型 Key 只在 Authorization header，Adapter 对返回值进一步脱敏。支持 HTTP 的主机仅 localhost/127.0.0.1；其他 Provider 必须 HTTPS。不同兼容 Provider 的 `max_completion_tokens`/JSON模式兼容性尚需真实账号验证；不支持时显式失败，不静默改变协议。

## GitHub Fine-grained PAT

操作者在 GitHub 自行生成 Fine-grained PAT，Resource owner 选择自己的账户，Repository access 只选择一个明确的个人测试仓库。最小权限为 Metadata read、Issues read-only；需要三个受控写工具时改为 Issues read/write。无 Contents、Administration、Members 权限需求。权限以 GitHub 官方端点说明为准，见 [Issues](https://docs.github.com/en/rest/issues/issues)、[Comments](https://docs.github.com/en/rest/issues/comments)、[Labels](https://docs.github.com/en/rest/issues/labels)。

PAT **只设置在 MCP Server 进程的 GITHUB_TOKEN 环境变量**。Web 进程不要设置此变量。真实模式强制拆分服务：

```powershell
# MCP 专用终端：先通过本地安全方式设置 GITHUB_TOKEN，勿粘贴到聊天。
$env:GITHUB_MODE = 'real'
$env:REPO_ALLOWLIST = 'your-owner/your-explicit-test-repo'
$env:DATA_DIR = 'data-real'
.\.venv\Scripts\python -m issue_agent.server --transport streamable-http --port 8022
```

```powershell
# 另一个没有 PAT 的 Web 终端，使用同一个数据目录。
$env:GITHUB_MODE = 'real'
$env:REPO_ALLOWLIST = 'your-owner/your-explicit-test-repo'
$env:DATA_DIR = 'data-real'
$env:MCP_URL = 'http://127.0.0.1:8022/mcp'
.\.venv\Scripts\python -m issue_agent.api
```

不要运行 `start.ps1 -Local` 来开启真实模式，该脚本刻意固定 Mock。默认 Compose 的内部后端网络禁止外部 GitHub 出站，也固定 Mock；真实集成使用上述独立 loopback 服务配置。本次未执行这些真实 GitHub 命令。

固定 REST origin 是 `https://api.github.com`，不提供可随用户输入更改的 GitHub base URL。API header固定`2022-11-28`，不追随 Issue 提供的 URL、重定向或 Link。写入只有在仓库是本人明确指定的测试仓库，并且逐项批准后才能进行。

## 本地信任边界

仅 loopback 或 Docker内部网络。会话 cookie 与 CSRF 防止跨站误触发，不等于账号登录、组织 RBAC 或标准 MCP OAuth。不要用反向代理暴露公网。DB卷含仓库文本和审计，宿主和共享UID被信任；不提供加密存储、防篡改审计或自动保留期。

`DATA_DIR` 用于数据隔离；不要让 mock/real 共用同一 DB。`REPO_ALLOWLIST` 支持逗号分隔，但这不是跨项目授权入口。重新配置 Allowlist 后 Server 在执行时重新核查，原审批不能放宽当前策略。
