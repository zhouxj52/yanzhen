# JiuwenSwarm 验收任务说明

本文件供使用者配置自己的 JiuwenSwarm 智能体，不会自动安装或改变现有平台配置。

先启动本地验真服务，再把 jiuwenswarm.config.example.yaml 中的 mcp.servers 项合并到现有平台配置。该配置形状来自官方 PyPI jiuwenswarm 0.2.3 安装包中的 jiuwenswarm/common/mcp_config.py；采用标准 stdio MCP 接口。

建议任务指令：

你负责组织软件验收。当前执行范围是内置报销系统，不承诺支持任意网站。先使用 analyze_requirements 分析用户需求；offline 表示固定规则演示，qwen 表示调用已配置的模型。给用户展示需求来源、角色和预期，获得对本次标准的确认后，调用 freeze_contracts。用户已经确认过的具体标准不必重复确认。

随后调用 run_acceptance，读取返回的运行编号，按需调用 get_acceptance_report 直到 completed 或 error。只能依据工具返回的真实证据描述结论，区分 pass、fail、blocked、unclear；不能把执行受阻或跳过视为通过。发现缺陷后使用 replay_defects 在新环境重放，再读取新报告中的 replay_comparison。不能通过放宽断言或更换角色消除失败。

服务使用本机固定端口，不接受 Agent 提供任意外部目标地址。Qwen 凭据只在服务端 .env 或环境变量中配置，不写入任务指令或 MCP 工具参数。

当前基础框架阶段默认关闭模型调用，使用 offline 即可完成联调，无需模型服务。

补充工具：用户明确取消任务时调用 cancel_acceptance；任务正在整理证据或已经结束时不可取消。导出前可以调用 verify_acceptance_evidence 校验清单与文件哈希，不能把哈希一致性当成制作者身份认证。

验证边界：check_mcp.py 会验证真实 MCP 握手和七个工具的完整链路。它不等于已验证完整 JiuwenSwarm 运行时、模型供应商配置或真实模型输出。

2026-10-23 补充：新增固定版本 TodoMVC 目标。分析 TodoMVC 需求时传 target=todomvc；执行时传 target=todomvc、scenario=upstream（上游内存存储）或 healthy（本地持久化修复对照），browser=true。报销系统继续使用 reimbursement。目标与契约语义不兼容时服务会拒绝执行。

报告中的 conflicts 关联实际冲突证据，reproductions 记录初始动作方案、逐次删减试验和独立确认。仅对 status=verified 的方案，可使用 replay_defects(run_id, contract_id) 在新环境验证精简步骤；不传 contract_id 时仍为整组重放。不能把未确认、受阻、不稳定或尚无动作适配说成成功复现。精简仅支持已适配动作，不是任意网站或任意 trace 自动精简。
