# 高频面试追问

## 协议与架构

1. MCP和普通HTTP API有什么区别？本项目在哪一行经过真正Client/Server边界？看client.connect与SDK Client，不是import Server。
2. 2026-07-28还有initialize握手吗？主协议改为请求级能力信息和server/discover；legacy 2025-11-25才走旧握手，两者都有实测。
3. MCP Host、Client、Server分别是谁？工作台/Agent是Host，MCPGateway包装官方Client，独立进程是Server。
4. 为什么不用官方GitHub MCP Server直接改名？解释范围、许可证、复用边界和独立业务代码。
5. 为什么同时实现stdio和HTTP？本地子进程调试与容器服务拆分；不是宣称远程生产授权。
6. 为什么不用LangGraph？这里循环和状态小而有界，额外编排依赖没有必要。

## 权限与审批

7. 只在Prompt写“不要写入”够吗？不够，模型目录排除写工具，Host校验，Server再次授权，写前claim。
8. 如果模型虚构审批通过怎么办？模型没有审批接口或token，输出字符串不改变数据库状态。
9. token绑定哪些字段？session、tool、repo和完整参数哈希；随机token仅存hash，短期有效且单次消费。
10. 同时点击批准两次怎么办？SQL BEGIN IMMEDIATE串行化状态转换；execution指纹唯一，最多一方取得写入权。
11. 参数改一个字符会怎样？有效凭证的hash不匹配使动作INVALIDATED，旧token不能再用。
12. 重启后token还有效吗？Server可以验证未过期APPROVED的hash，但Web不持久化明文token，不自动恢复发送；PENDING/结果/幂等记录持久化。
13. 为什么不暴露删除工具来展示拦截？危险能力根本不实现，未知工具直接BLOCK。
14. 本地cookie/CSRF等于生产鉴权吗？不等于。没有账号认证、OAuth、租户隔离或审计防篡改。

## 可靠性

15. GitHub评论能做到exactly-once吗？没有通用幂等key，响应丢失后无法同时保证必达与不重复；本项目选择一次发送和UNKNOWN人工核对。
16. claim成功后进程立即崩溃会怎样？可能没发送但保留EXECUTING；可用性代价，不能自动重试。
17. 401、403、429、5xx怎样区分？参数/权限不重试，限流停止，读传输/5xx最多三次尝试，写一次。
18. 分页Link指向其他主机怎么办？不跟随任意Link；使用固定路径的page/per_page，最多三页。
19. 24次请求预算包括重试吗？包括。同run_id由Server持久化计数，模型不能传入预算控制字段。
20. 多个动作部分成功怎么办？没有GitHub跨操作事务，不回滚已成功评论；逐项结果展示。
21. SDK为什么曾让409异常失效？AnyIO退出包裹ExceptionGroup；connect先暂存业务异常、正常清理后重抛，回归测试证明修复。

## Agent与评测

22. 什么证明是真正Tool Calling而非规则？实现了兼容Provider请求、动态MCP schemas、模型工具消息回传与有界循环；但本次真实模型未运行，只有实现和Scripted控制流测试。
23. 第四轮后怎么办？允许一次纯结构化答案响应，不再提供工具；如果仍返回工具调用则停止。
24. Offline为什么不叫模型Agent？它是固定规则与固定读流程，无模型推理；界面和报告单独标识。
25. 50/50代表什么？合成回归达到预期，包括拒绝；不是工具全部成功、真实模型准确率或真实用户收益。
26. 工具调用成功率为什么不是100%？分母有故意非法、越权、限流和超时案例，正确拒绝不会算成功执行。
27. Token/成本怎么测？只采用Provider实际usage，不编造离线token，不用猜测价格。
28. 覆盖率80%是语句还是分支？分别报告；checks.json按covered_branches/num_branches计算真正分支覆盖。

## 产品与复盘

29. 为什么不用Issue Forms？新Issue字段收集可以优先Forms，本项目的价值假设在已有非结构化Issue和上下文整理，需要真实用户验证。
30. 用户为什么敢批准？可看到具体repo、Issue、正文、工具、影响、hash和期限；仍不能完全防止人类误批准。
31. 是否做过真实用户测试、真实GitHub写入？本次没有，只有计划和Mock闭环，分层说明。
32. 下一步最值得做什么？真实模型只读样本验证、个人测试仓库的明确审批写入、3-5人可用性观察；不要先扩张危险工具范围。
