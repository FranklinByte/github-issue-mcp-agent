# 实际验证记录

## 2026-10-16 维护验证

修复 `list_open_issues` 混有 Pull Request 时，先过滤 PR 再计算页长导致后续 Issue 丢失的问题。分页优先读取响应 Link 的 next 标记；没有 Link 时使用过滤前页长。仍最多三页，不跟随响应中的任意 URL。

新增 4 个回归场景：混合 PR/Issue 且有 next、无 Link 的满页、只有 prev 的末页、三页上限。当前 103 项测试全部通过；Ruff 格式与静态检查、mypy、依赖检查通过。综合覆盖率 92.42%，独立分支覆盖率 88.4375%。

重新执行了官方 SDK stdio MCP smoke（工具发现、读取、无审批拒绝、批准后写入、重复写入拦截），以及 50 条固定离线案例：50/50 符合预期，未经审批写入 0。GitHub 业务操作仍使用 Mock，没有调用真实模型或真实 GitHub；本次未重跑 Docker、浏览器和云端 CI。

本次原始证据：[检查结果](../artifacts/maintenance-2026-10-16/checks.json)、[测试输出](../artifacts/maintenance-2026-10-16/pytest.txt)、[MCP smoke](../artifacts/maintenance-2026-10-16/mcp-smoke.json)、[离线评测](../artifacts/maintenance-2026-10-16/offline/results.json)。下面是保留的历史冻结记录，不代表重新执行。

## 2026-09-07 冻结验证

冻结日期：2026-09-07（Asia/Singapore）。所有本项目业务测试使用Mock GitHub；真实模型、真实GitHub业务调用与写入均未执行。公开仓库的开源调研请求另计，不是业务集成测试。

| 层级 | 实际结果 | 原始证据 |
| --- | --- | --- |
| pytest | 99 passed | [pytest.log](../artifacts/pytest.log)、[JUnit XML](../artifacts/pytest.xml) |
| Ruff格式/静态检查 | 全通过 | [ruff-format.log](../artifacts/ruff-format.log)、[ruff.log](../artifacts/ruff.log) |
| mypy strict | 13个源文件通过 | [mypy.log](../artifacts/mypy.log) |
| 依赖一致性 | uv pip check通过 | [dependencies.log](../artifacts/dependencies.log)、uv.lock |
| 综合coverage | 92.41%（语句与分支合并） | [coverage.json](../artifacts/coverage.json) |
| 真正分支覆盖率 | 283/320 = 88.4375%，目标80% | [checks.json](../artifacts/checks.json) |
| MCP stdio | 九工具发现、读取、无审批拒绝、一次批准与重复拦截 | [mcp-smoke.json](../artifacts/mcp-smoke.json) |
| MCP协议 | 主路径2026-07-28；legacy握手2025-11-25 | 同上；test_mcp_http.py另测真实loopback HTTP |
| 固定离线评测 | 50/50达到预期，未经审批写入0 | [results.json](../artifacts/offline/results.json)、[逐案例JSONL](../artifacts/offline/cases.jsonl) |
| Docker | 实际构建启动，两个容器UID10001，healthy，Web可访问，HTTP MCP链路通过 | [Docker记录](../artifacts/docker/verification.json) |
| Docker审批/重启 | 无审批POST被阻止；批准新增一条评论；重复409；重启保留PENDING/SUCCEEDED；无额外写入 | 同上 |
| 浏览器 | Chromium桌面1440x1000、手机390x844、窄屏320x740、宽屏1920x1080，无JS异常或横向控件溢出 | [UI记录](../artifacts/ui/verification.json)、同目录PNG |
| 真实Provider | 未运行，无Tool Selection Accuracy/usage/cost报告 | Provider Adapter及Scripted测试不冒充真实模型 |
| 真实GitHub业务API | 未执行 | REST Adapter使用MockTransport验证 |
| 真实GitHub写入 | 未执行 | 未创建外部仓库、Issue或评论 |
| 云端GitHub Actions | 已配置，未执行 | [.github/workflows/ci.yml](../.github/workflows/ci.yml) |
| 真实用户测试 | 未执行 | [测试计划](user-testing-plan.md) |

## 评测解释

离线工具调用成功率70/92（76.09%），因为分母含预期失败/拦截；参数Schema通过率18/22（81.82%），因为样例刻意包含缺参、类型和越权字段。权限判定准确率、标记攻击的预期拦截率和两个重复抑制场景均100%；只适用于当前合成样本。

该次本地混合案例延迟p50为24.743ms、p95为1278.831ms，最多四轮工具调用。任务场景包含stdio子进程启动，其他case重用连接；不能与生产模型网络时延比较，重跑会变化。最新数值以[离线报告](../artifacts/offline/report.md)为准。

## 可复现命令

`python scripts/verify.py`按顺序运行格式、Lint、类型、依赖、pytest、官方SDK smoke、离线评测，保存每条命令exit_code和stdout/stderr。`python scripts/docker_verify.py`只操作这个Compose项目，保存实际容器和Mock数据库变化；`python scripts/ui_verify.py`实际点击按钮、查看状态并截图。

不把“可以启动”写成“已验证所有外部系统”。Cloud CI、PAT权限在真实仓库的效果、Provider兼容性和用户价值仍是后续独立验证层。
