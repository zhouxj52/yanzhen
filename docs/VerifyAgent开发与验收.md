# VerifyAgent 开发与验收记录

更新日期：2026-10-29。本次为增量重构的纵向切片，真实模型及 Swarm 单规划角色已实跑，现已新增 openJiuwen Workflow 四角色协作；完整 Swarm 群智与真实模型竞赛对照实验未完成。

## 作品目标与三个创新

AI 生成软件时，同一个工具可能同时修改业务代码和测试，测试通过不能直接证明需求满足。验真面向验收交付的开发者、测试人员和项目负责人，独立锁定标准，再用软件实际行为核对。

1. **需求锁定**：`C=(P,A,Q,N,S)` 表达前置条件、动作约束、业务后置条件、不变量和出处；人工确认后冻结，版本不可覆盖。模型理解需求、规划操作，确定性断言引擎决定结论。
2. **跨层证据图**：关联页面、网络响应、独立读取、真实轨迹和重放。HTTP 200 或成功提示本身不代表业务成功。缺少观测为 BLOCKED，无法比较为 UNCLEAR。
3. **保持标准的修复复验**：执行器修复只允许调整真实失败动作的定位和超时；业务代码修复本轮以外部已部署版本为输入，保持原契约、身份和隔离协议，全项检查通过才能标记修复复验成功。

这些机制已有实现及受控验证，尚无大规模对照数据证明其优于其他测试 Agent。

## 审计与保留

修改前记录仓库文件摘要和模块判断，运行原有 55 项测试并保存基线。内部文件：`.tmp/verifyagent-audit.json`、`.artifacts/refactor-baseline.xml`。

保留原目录式契约、报销 / TodoMVC 适配器、任务队列 / 取消 / 重启恢复、原断言器、精简算法、证据 ZIP、原工作台、原 API 和 7 个 MCP 工具。没有删除原内核测试，也没有把旧业务目录包装成通用推理。

当前前端聚焦“开始验收”和“验收记录”，演示剧场与开源实测展示页已移除。外部开源应用评测集中为 `scripts/benchmark_upstream.py` 单文件入口，包含 31 条检查、目标启动、结果报告及证据核查。字体改为本地 Noto Sans SC 可变字体，工作台正文与辅助信息统一使用深色文字，最小字号 14px；全流程浏览器检查覆盖展开详情、禁用控件和手机布局。

新增 `yanzhen/verifyagent/` 内核。旧修复审查入口另外加固：调用方提交的 `witnessed_action` 不再当作见证，改为读取归档的实际执行结果。

## 系统架构

```mermaid
flowchart LR
    U[原始需求与授权目标] --> S[真实模型生成候选]
    S --> H[人工审阅与版本冻结]
    H --> O[观察真实页面或接口]
    O --> P[模型规划一个动作]
    P --> A[受控工具与逐动作审批]
    A --> O
    A --> E[执行证据和冻结探针]
    H --> V[独立确定性断言]
    E --> V
    V --> G[结论和证据图]
    G --> R[真实轨迹精简与独立重放]
    R --> F[同标准修复复验]
```

`Bundle` 保存需求、来源、发现资料、版本、父版本及哈希；`Run` 保存冻结快照、实际动作、观测、审批、事件、模型调用和结果。Observe → Plan → Act → Verify → Replan 传递真实状态与工具错误，界面不显示伪造的进度或思考。

| 模块，均位于 `yanzhen/verifyagent/` | 实现职责 |
| --- | --- |
| `schema.py` | 严格契约、探针、断言、身份、动作与运行 Schema，禁止未知字段。 |
| `planning.py` | DeepSeek / Qwen 真调用、只读发现、Schema 修正反馈、逐步决策；官方 Swarm E2A 桥接。 |
| `repository.py` / `service.py` | 原子保存、冻结版本保护、有限队列、取消恢复、精确动作审批。 |
| `executor.py` / `security.py` | 真实 Chromium / httpx、12 类 DSL、白名单 / 跳转 / 路径校验、身份引用与脱敏。 |
| `engine.py` / `oracle.py` | 闭环、观测、预算、确定性比较、操作完成条件、失败指纹和证据图。 |
| `replay.py` / `repair.py` | 执行器证据绑定、可解释删减、双次重放、执行器修复审计。 |
| `exports.py` / `budget.py` | ZIP / SHA-256、请求前持久预留成本、错误及 Token 记录。 |
| `api.py` | 新增 `/api/verify/*`，保留旧 API。 |

`web/verifyagent.*` 提供四步工作台、实时事件、操作审批、图、历史、精简和复验。`mcp_server.py` 增加 4 个通用工具，总计 11 个；通用冻结和写审批保留在人类操作界面。

Schema 不依赖业务目录。动作覆盖 navigate、click、fill、select、wait_for、assert_visible、assert_text、http_request、assert_status、assert_json、reload、compare_state。工具断言只产生观测，不能代替冻结断言宣布通过。

短暂的成功提示可用检查点核对，但契约必须包含独立终态业务观测，禁止只用成功提示或保存前状态作为通过依据。模型若提前结束却缺少必须操作，内核会将遗漏反馈回模型；人工固定计划则明确受阻。

## 安全与适用边界

- 接受服务端白名单中的精确本机、私网和公网测试来源，限制目标应用路径；公网域名必须全量解析到公共 IP，每次运行固定 TCP 连接地址，同时保留 Host、TLS SNI、证书验证和域名 Cookie。浏览器通过解析规则固定 IP；跨来源跳转仍拒绝。
- 浏览器上下文、API 客户端按身份隔离；不接收任意脚本、eval、Shell，阻止下载、WebSocket 和越界请求。
- click / fill / select 与非 GET/HEAD 请求需审批，审批绑定动作、运行、目标、契约及有效期；不得用调用方字符串伪造实际执行。
- 身份只引用 `YZ_VERIFY_SECRET_*`；响应、轨迹、截图对已知凭据脱敏。
- 新会话不等于后端重置。变更操作精简要求目标明确支持命名空间隔离；测试应用实现 `X-Verify-Sandbox`。
- 有步骤、时间、模型次数、网络请求和响应大小上限；变更动作不自动重试。

账号、选择器或 API 描述可由人提供，记录在目标或发现资料中。本轮只读发现使用了人工提供的 `api/schema`，不能据此声称自动发现了所有接口。

## JiuwenSwarm 的实际运行

核对官方 `jiuwenswarm==0.2.3`，独立可选环境位于 D 盘。代码使用真实发布的 `E2AEnvelope`、`parse_agent_server_wire_chunk`，以及 `chat.send` / `agent.plan` 消息，没有编造 SDK 类。

最初的 WebSocket 测试使用明确的协议替身，只证明格式兼容。随后新增 `swarm_server.py`，已运行真实官方 `JiuWenSwarm.process_message`、会话队列、历史和 `AgentAdapter` 协议，规划请求实际到达 DeepSeek。`agent_ref.id` 仅作路由身份，没有把它当作自定义 Agent 选择器。

结构为：E2A → 官方 facade / 会话队列 → 本项目 JSON 规划适配器 → 真实 DeepSeek → Schema 校验 → 本地受控工具。适配器不注册浏览器、文件、Shell 或其他原生工具；总验收循环、审批与确定性判定仍由 VerifyAgent 控制。没有启动默认的通用 Coding AgentServer，也不声称完成了跨角色协作。

适配器实现官方协议，通过版本固定的 `_ensure_adapter` 受保护扩展点接入；升级 SDK 必须复核兼容。运行时限定 `chat.send`、固定 D 盘工作区、UUID 会话、私有本地凭据，并关闭记忆、A2UI 及自动提取；配置变化时拒绝继续。客户端校验运行时标识、空原生工具列表、共用账本与费用上限，拒绝未计量的其他运行时。

实际持久化测试 run `da1fc5607ccc46f783186d130fbd7935`：7 次真实规划请求、6 个动作，独立判定 FAIL。实际页面漂移 run `c4a53bf6dde449ad9609f1d40dbd8b90`：8 次请求、7 个动作，包含一次真实定位超时；模型改用新按钮后原契约 PASS。官方会话历史位于 D 盘 `.artifacts/swarm-runtime/agent/sessions/`。

来源：[官方仓库](https://github.com/openJiuwen-ai/jiuwenswarm)、[0.2.3 发布包](https://pypi.org/project/jiuwenswarm/0.2.3/)。

## 运行演示与验证

启动两个前台服务的方法见根目录 README。测试目标为 `examples/verifyagent/app.py` 1.0，使用合成身份和每次执行的新命名空间，没有生产数据。

权限演示用两身份确认订单归属，再验证本人可读、他人订单按已审阅假设返回 403。`auth_bug` 故意缺失边界，`healthy` 正常。

持久化演示真实填写、保存、刷新和重新读取。`persistence_bug` 返回成功却不存储，`healthy` 正常。缺陷位于目标应用，验证器没有按缺陷名称返回结果。

```powershell
# 明确授权可丢弃测试数据中的操作；这些命令默认使用人工样例
.venv/Scripts/python.exe -m yanzhen verify-demo --case authorization --variant auth_bug --approve-local-fixture-writes
.venv/Scripts/python.exe -m yanzhen verify-demo --case persistence --variant persistence_bug --approve-local-fixture-writes

# 自动化测试，包含真实 HTTP / Chromium 集成测试
.venv/Scripts/python.exe -m pytest --basetemp=D:/openjiuwen/.tmp/verifyagent-final-tests --junitxml=.artifacts/verifyagent-final-tests.xml

# 真实浏览器完整产品流程与三种宽度
.venv/Scripts/python.exe scripts/check_verifyagent_ui.py

# 7 个内核样本、真实精简及同标准复验
.venv/Scripts/python.exe scripts/benchmark_verifyagent.py --approve-local-fixture-writes

# MCP 握手及原验收 / 重放 / 取消 / 导出联调
$env:YZ_PORT='8767'
$env:YZ_ARTIFACTS_DIR='D:/openjiuwen/.artifacts/verifyagent-service'
.venv/Scripts/python.exe scripts/check_mcp.py
```

真实模型演示增加 `--provider deepseek --allow-model`，需要明确启用模型、密钥及费用配置。终端会展示候选，键入 FREEZE 才冻结。人工样例不冒充模型输出，协议 Mock 仅用于隔离单元测试。

可选 Swarm 环境需安装 `.[swarm]`，所有环境和缓存放在 D 盘。配置 `YZ_SWARM_WS_URL=ws://127.0.0.1:8774`、`YZ_SWARM_AGENT_ID=verifyagent-json-planner`、`YZ_SWARM_PLANNING_ONLY=1`、`YZ_SWARM_LOCAL_RUNTIME=1`，并在本地生成独立的随机 `YZ_SWARM_PROXY_KEY`（至少 32 字符，不是供应商密钥）。工作台与运行时共用 `.env`、产物目录和 5 元账本。当前已安装环境可在第三个终端启动：

```powershell
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component swarm -EnableModel -PythonPath D:/openjiuwen/.cache/swarm-runtime/Scripts/python.exe
```

工作台所在环境也需有可选 SDK 的 E2A 模块。当前主环境通过 D 盘 `.cache/swarm-client` 的 `PYTHONPATH` 使用它；新安装可直接安装项目可选依赖。模型演示选择 `--provider jiuwenswarm` 即可。默认不开启模型。

## 真实模型纵向切片

1. DeepSeek 真实生成持久化候选。前 5 次开发调用有结构或来源校验错误并被拒；第 6 次生成有效候选。这期间修改过提示和 Schema，不能把比例当作标准化契约生成有效率。
2. 工程审阅修正保存后观测时点、status 定位和相对导航，保留原候选，形成第 2 版。用户在对话中明确确认后冻结；不能称为未经编辑的全自动契约。
3. 第一次模型执行遗漏必须的导航，独立内核返回 BLOCKED，失败证据保留。随后为规划器增加操作遗漏反馈，**没有改动冻结契约**。
4. 第二次真实模型执行了 6 个动作，独立断言得到 2 PASS、2 FAIL，契约结论 FAIL：保存后页面正确、成功提示存在，刷新和独立 GET 均为空。
5. 从该真实轨迹进行独立重放，2 次确认相同指纹。6 步均受冻结约束要求，最终仍为 6 步；没有为了演示精简率删除必须步骤。
6. 正常部署执行相同轨迹并使用同一契约，全部原断言 PASS，修复复验 verified=true。没有自动修改产品源代码。

模型执行 run：`8d7609133989489198dbf693f8ec0ee6`；原始受阻 run：`3fd2b80680a94322aa5415a0e57d7caa`。冻结 SHA-256：`87b494aa5602e242fa88a2a0d2b8aa4fad56991a33e750055e3e7de19b7efc46`。

成功直接模型执行阶段 7 次调用，23,524 输入 / 538 输出 Token，约 12 秒，不含契约生成和人工等待。整个开发验证共 44 次请求预留，保守累计上界 **3.140580 元**，小于用户授权的 5 元；按全部返回 Token 和峰值单价计算的费用上界为 0.405452 元，实际账单由供应商确定。未使用的预留不退回预算，密钥不入库。

真实 Swarm 页面变化测试中，测试站在鼠标进入按钮时替换 DOM 并把“保存”改为“应用更改”。首次点击产生 Playwright 超时，错误进入轨迹；下一轮模型观察新按钮并重新规划，最终 4 项原断言全 PASS，同标准修复复验 verified=true。没有模型返回固定响应。

该测试第一次尝试也暴露了相对 / 绝对 URL 被当作不同必须操作的问题，预算耗尽后保持 BLOCKED。现已按授权目标解析 URL 后比较等价地址，补充回归；冻结预期值与断言没有变化。失败运行保留在 `.artifacts/real-swarm-drift-blocked.json`。

本机证据：`.artifacts/real-model-spec.json`、`real-model-reviewed-candidate.json`、`real-model-initial-blocked.json`、`real-model-run.json`、`real-model-replay-repair.json`。公开精简记录见 `benchmarks/results/real-model-integration.json`。

## 自动化与小样本实验

当前全量测试 **112 passed**（包含可选 SDK 协议测试及新增只读连接检查）；原有 55 项没有删除。最新 XML 位于 `.artifacts/challenge-final-tests.xml`，此前版本记录保留。最终 UI / MCP 状态集中在 `benchmarks/results/verification-summary.json`。

首次使用入口改为“验收我的项目 / 先体验一个示例”，支持 GitHub / ZIP / 本地目录与运行地址，明确区分源码预检和功能验收；清单以中文可读形式展示，高级 JSON 折叠。界面按阶段展示，不提前显示空执行或空结果。连接检查读取真实授权目标，不调用模型，也不生成验收结论。

网页流程验证了版本保留、冻结、逐动作审批、实际 FAIL、矛盾图、真实精简、正常部署同标准 PASS、ZIP 全文件 SHA-256，以及 1480 / 900 / 390 宽度无横向溢出、页面错误为 0。该脚本调用模型为 0。

7 个本地 API 内核样本 7/7 与预期一致：

| 指标 | 数值和限制 |
| --- | --- |
| 受控缺陷检出 | 3 / 3：越权、备注丢失、负库存。 |
| 正常误报 | 0 / 3；另 1 个 503 依赖不可用返回 BLOCKED。 |
| 精简 | 1 个 API 案例计划 2 → 1，50%，新环境确认 2 次。固定探针不计入计划动作数。 |
| 无效修复拦截 | 1 / 1 哈希篡改候选被拒；更多身份 / 轨迹攻击见测试。 |
| 同标准复验 | 正常部署全项通过，未自动生成补丁。 |
| 本轮平均耗时 | 约 566 ms，仅 7 个本机 API 内核样本，没有模型及网页开销。 |
| LLM 消耗 | 该矩阵为 0，与真实模型联调分开记录。 |

库存是开发保留域，证明新 URL / 数值条件无需增加 adapter，但参与过调试，不算严格外部盲测。

对照 A（人工固定 DSL，保留内核标准）已运行。对照 B（静态 LLM，无冻结与重规划）、Full Swarm，以及移除重规划 / 跨层证据 / 精简 / 修复审计四项消融，**均未运行**。真实 DeepSeek 单案例也不能代替上述实验。没有独立标注语料，因此需求覆盖率、契约生成有效率未评估。

结构化数据在 `benchmarks/results/`，本机完整产物在忽略的 `.artifacts/`。`.github/workflows/verify.yml` 已添加，远端 CI 未运行。不声称真实项目检出率或相对竞品提升。

## 最终 12 问的当前验收状态

| 问题 | 状态 | 代码、测试与证据 |
| --- | --- | --- |
| 1. 接收目录外新需求 | PASS（受控范围） | `schema.py` / `planning.py` 不依赖目录；真实模型持久化候选；`test_generic_contract_not_bound_to_business_catalog`。 |
| 2. 不写 adapter 验证新 Web 项目 | PARTIAL | `executor.py` 真实操作独立页面；`test_real_browser_ui_api_refresh_conflict`。没有外部陌生 Web 项目盲测。 |
| 3. 真实 LLM 自主规划 | PASS（单案例） | `ModelPlanner` 真调用，6 个动作和 7 次规划记录；`real-model-integration.json`。契约有人工编辑。 |
| 4. Swarm 真实编排 | PARTIAL（单规划角色实跑） | 官方 facade / 会话队列已处理真实模型请求，见 `swarm_server.py` 和真实 Swarm 两个 run；总验收循环由 VerifyAgent 控制，跨角色协作未实现。 |
| 5. 页面变化或失败后重规划 | PASS（受控页面） | `real-swarm-drift-run.json` 中真实点击超时，下一次模型选择“应用更改”，原契约 PASS；相同场景另有真实浏览器回归。 |
| 6. 冻结契约和实际证据判定 | PASS | `oracle.py` / `repository.py`，缺失 / 伪造 / 类型不兼容 / 哈希变化测试和真实模型 FAIL。 |
| 7. UI / API / 实际状态冲突 | PASS（受控样本） | 真实保存提示与回显存在，刷新 / GET 空值；浏览器集成测试和真实模型证据。 |
| 8. 从真实轨迹提取和精简 | PASS（限定范围） | `replay.py`，Web / API 重放双确认；仅单契约，受冻结操作约束，不声称全局最短。 |
| 9. 防修改断言制造假成功 | PASS | `repair.py`、旧入口加固、哈希 / 身份 / 轨迹 / 跳过操作测试。 |
| 10. 隔离修复复验 | PASS（外部部署） | 新会话及后端命名空间，正常部署原契约全项 PASS；没有自动代码修复。 |
| 11. 开发外新项目或保留集 | PARTIAL | 库存域独立但参与过调试；严格盲测项目 NOT TESTED。 |
| 12. 可重复量化实验 | PARTIAL | 7 案例内核矩阵及真实模型单案例数据存在；B / Full / 消融 / 需求覆盖率未运行。 |

## 剩余优先级

下一步优先用独立标注的需求和陌生目标运行 A / B / Full 与消融，报告分母与失败样本；扩展 Swarm 的规范生成 / 诊断角色协作并保持共用标准和费用边界。

再扩展多契约精简、复杂登录、目标重置协议和自动代码修复。所有声明以实际执行结果为准。本次扩展与基础版本位于 `codex/verifyagent-ink-6` 分支。


## 多来源接入与 openJiuwen 优先适配（2026-10-27）

入口现在提供运行地址、公开 GitHub、ZIP、本地服务器目录四种材料。GitHub 分支解析为固定提交后下载；ZIP 校验路径、链接、重复及文件大小；目录受服务端允许根目录约束。内容复制为独立快照并保存文件 SHA-256，常见密钥文件、依赖和缓存排除。Python 只进行 AST 语法分析，不执行模块；配置与结构预检不输出业务验收 PASS。源码与部署来源的关联仍由用户声明，不是构建来源证明。

纯静态 HTML 可以启动本地只读文件服务，关闭外部连接并继续真实浏览器验收。动态项目先预检，再按 README 启动依赖与服务，填写实际地址；没有自动安装或运行任意项目脚本。源码报告和文件清单加入验收 ZIP 的完整性清单。

本地浏览器已实际验证：上传 ZIP → 源码快照 → 静态预览 → 人工样例契约冻结 → 实际填写 / 保存 / 刷新 → PASS → 导出并核对源码清单；另验证目录中的真实 Python 语法错误和公开 GitHub 固定提交导入。UI 宽度 1480 / 900 / 390 / 320 无横向溢出，页面错误为 0，模型调用为 0。记录 `.artifacts/intake-ui-check.json`；可通过 `scripts/check_project_intake_ui.py --with-github` 重现。

竞赛首选入口是官方 `openjiuwen==0.1.19.post2` 的 Workflow / WorkflowComponent / create_workflow_session。每次需求分析和规划实际执行 request → model_planning → schema_validation → return，模型节点沿用本项目计量客户端与严格 Schema；工具、冻结标准、审批、重放和独立 Oracle 仍由验真负责。底层通过 `YZ_OPENJIUWEN_MODEL_PROVIDER` 选择 DeepSeek 或 Qwen，不把框架当作模型供应商，也未宣称完整多角色 Swarm。安装脚本默认安装 SDK，CI 配置也新增此集成测试；远端 CI 本次尚未运行。

真实调用联调完成 1 次官方 Workflow → 已配置 DeepSeek 的规划请求，四节点都有完成记录，费用账本只增加 1 次，总计 57 次预留、保守上界 3.975344 元，未超过既有 5 元 / 60 次限额。记录 `.artifacts/openjiuwen-real-planning.json`。这是链路联调，不是端到端自主验收成功率。公开目标另用本项目 GitHub 公共 API 实际验证 HTTP / 浏览器读取成功与 IP 固定，记录 `.artifacts/public-project-connectivity.json`；静态预览和 TLS Cookie 测试不能代替复杂登录或跨域部署验收。


## 反例挑战与角色协作（2026-10-27）

首版接入正常验收已通过、单契约且有源码快照的静态 HTML/JavaScript 项目。`mutations.py` 以固定 Esprima 4.0.1 AST 识别存储写入、比较边界和相等条件，补丁只能来自服务器重新计算的候选，变异前后均检查语法。文件超过限额、现代语法不支持时明确跳过。原源码哈希和冻结契约不变，不能改断言或把脱敏占位符作为重放输入。

`challenges.py` 随机打乱正常对照与单独变异副本，事先提交带随机 nonce 的分配哈希。执行目标只有匿名名称和随机环回端口，不携带项目快照引用、补丁或标签。匿名由模型输入和工具边界实现，不对有服务器文件权限的人保密。执行后验证承诺与原源码/契约完整性，再揭晓结果和导出逐次证据 ZIP。正常对照未通过不计算观察检出比例；存活、受阻、待澄清、未执行分别保留。语法变异可无效或等价，观察检出比例不是已标注缺陷召回率。

`team.py` 使用固定官方 SDK 的独立 Workflow 节点：需求分析、反例挑战、执行规划、证据审查。前三个角色分别调用真实模型，最后一个是确定性操作义务审查；缺少必须操作时交回执行者修正规划。角色只能引用冻结探针，不能修改标准。业务最终结论继续由 `oracle.py` 和实际探针计算。已校验分析只在同一运行/契约中缓存，角色共享原有每次运行调用上限与持久费用账本；实际发出的请求和预算拒绝分开记录。原 JiuwenSwarm 单规划 facade 未变，不把该 Workflow 说成完整 Swarm 群智运行时。

前端入口位于原工作台：先体验示例 → “这套验收，能识破假保存吗？” → 人工确认正常基线 → 实际执行 → 结果中的反例挑战。默认固定真实轨迹模式不调用模型。协作和对照模式使用真实模型，新规划写入仍逐动作确认。挑战可取消、刷新恢复、导出；历史中可回看每个匿名目标的真实角色事件和证据。

本地 UI 已实跑：正常对照 PASS、删除存储写入 FAIL、边界变异存活；源码和原契约保持不变，ZIP 全文件哈希通过，1480/900/390/320 无页面横向溢出和脚本错误。可运行 `scripts/check_counterexample_ui.py` 重现，默认不调用模型。

真实模型挑战 `608640ad4f214e7aa3adba62e69fd72e` 完成正常/存储写入变异两个匿名目标。两次均经过官方四角色 Workflow，正常 PASS、变异 FAIL，共 14 次真实模型请求，两个运行合计约 36.3 秒。新增调用后，共享账本累计 71 次预留、保守上界 4.758062 元；经用户明确同意，次数上限从 60 调整为 100，总费用上限仍为 5 元。该样例是人工编写的测试源程序，不是陌生开源项目盲测。公开精简记录见 `benchmarks/results/counterexample-collaboration.json`；完整证据在忽略的 `.artifacts/real-role-campaign.json` 及对应挑战 ZIP。

单角色/多角色对照已实现相同每次请求与时间上限，在全新浏览器上下文中运行相同变异，只对共同完成的变异比较，未配对项单列。实际请求数、Token 与耗时记录在报告中；请求上限相同不表示实际费用相同。本轮对照使用显式模型传输替身、真实官方 SDK 与真实浏览器，单/多角色各完成正常和存储变异，均得到正常 PASS、变异 FAIL。付费模型对照、消融和有效变异独立标注尚未运行，不宣称多角色更优。


## 2026-10-28：真实项目评测与需求追溯

评测仍集中于 `scripts/benchmark_upstream.py`，默认 v3 协议覆盖 4 个仓库、5 个应用、49 条固定流程检查。新增源码按 `benchmarks/upstream-sources.json` 固定提交、Git blob、SHA-256 与大小，只下载到忽略缓存；没有安装或执行新增项目的包脚本，也未修改业务源码。运行前保存全部契约、输入动作、预期标签、分母与协议哈希，失败/未执行/受阻始终留在报告，子集有明确标识。

完整运行编号 `8e9afb8a1fe84daaaaebd05a9abc06d1`：Petclinic 22 PASS，Juice Shop 8 PASS + 1 FAIL，Expense Tracker 7 PASS，Form Validator 2 PASS + 5 FAIL，MDN Shopping List 4 PASS；43 条正常检查通过、6 条缺陷用例检出，49/49 与预注册标签一致。6 条缺陷用例分属 2 个缺陷组，不能算成 6 个独立漏洞。表单分支问题先由源码审阅标注，再由不使用验真 ToolExecutor/oracle 的原始浏览器步骤核对；没有独立人工标注组，也不是陌生目标盲测。累计执行耗时约 75.2 秒，模型请求 0，共享付费账本不变。公开记录为 `benchmarks/results/upstream-fixed-plans-v3.json`。

试跑 `expense-balance` 的旧标准错误地认为小数金额可提交，实际被原生 number 输入整数步长阻止，得到 FAIL。旧运行 `a424e93b52cd4ea4a133d25568f9b510` 与原契约哈希保留；新协议分别检查整数混合收支与小数输入的原生拒绝。旧试跑不更改标签、不并入正式计分。

本机 `.artifacts/upstream-evaluations/8e9afb8a1fe84daaaaebd05a9abc06d1/` 包含预注册 protocol/commitment、独立参考截图、HTML/JSON、逐条证据组成的 evaluation.zip。`--audit` 核对协议分母、预期标签、冻结哈希、实际运行结论、步骤/模型计量、全部封存观测与 ZIP 哈希。来源与已运行部署的关联对旧后端仍由操作者声明；不宣称构建产物证明或上游官方全套成绩。复现命令见脚本文件头和 README，旧协议用 `--suite legacy`。

`coverage.py` 根据原文精确引用生成 `literal-requirement-traceability-v1`：需求句段 → 冻结断言 → 该断言所属流程的实际步骤 → 断言直接使用的封存观测。保留原文起止位置、部分未关联文字、前置条件、含歧义的重复引用，区分已验证、失败、受阻、待澄清、未覆盖、部分未关联及未执行。证据必须与运行/契约/探针/观测阶段一致，核对哈希并独立重算断言；缺少可信必要操作不能计为已验证。文字引用不是业务语义完整覆盖率，相关说明在页面、JSON 与 README 中保留。

确认清单前可查看关联预览；结果页支持筛选、展开真实步骤/截图/直接观测值。每次运行的 ZIP 新增 `requirement-coverage.json` 并纳入 manifest；旧归档按冻结快照计算只读下载，不重写旧 ZIP。普通运行把运行编号写入 URL，刷新后恢复。没有新增导航或恢复已删除的演示剧场/开源实测页。

验证：129 项自动化测试通过（5 条上游依赖弃用警告）；新增 17 项覆盖漏项分母、只引用前置条件、部分/重复引用、篡改观测或冻结标准、缺少必要操作、旧归档兼容与评测标签/分母防改。`scripts/check_requirement_coverage_ui.py` 已实际执行有持久化缺陷的本地测试站，确认失败与额外未覆盖 PDF 需求同时显示，筛选、截图链接、ZIP 哈希和刷新恢复通过；1480/900/390/320 宽度无横向溢出、无页面错误、模型调用为 0。


## 2026-10-29：工作台视觉与阅读流程

工作台改为单独加载 `verifyagent-atelier.css`，配合本地 `verifyagent-icons.svg`，避免旧版 style/studio/glass 多层覆盖。使用冰白 / 墨蓝主色、高对比正文，以及仅模糊背景、保持前景文字清晰的磨砂玻璃；本地 Noto Sans SC、最小 14px 字号与原有两项导航保留。

首页重排说明与流程示意，四种材料快捷入口会实际选中对应接入方式；表单、步骤条、示例、需求追溯和历史列表采用统一间距、边框与控件样式。结果统计直接来自实际 Run/coverage，实际值与冻结预期并排显示；完成后默认收起执行过程，目标地址、版本、状态和再次执行入口仍可见。历史列表增加只读本地搜索，模型预算与验收裁决逻辑未改。

浏览器回归：`check_verifyagent_ui.py`、`check_requirement_coverage_ui.py`、`check_counterexample_ui.py`、`check_project_intake_ui.py` 全部通过，覆盖审批、真实失败、复现、修复复验、源码导入、反例挑战及 ZIP 哈希；本轮未启用在线 GitHub 导入选项。只读视觉检查覆盖 1480/1280/1090/1024/900/840/768/660/390/320，未发现页面错误、根页面横向溢出或低于 14px 的可见文字。四种快捷入口和历史查询已实际点击验证，模型调用为 0。截图与检查记录位于忽略的 `.artifacts/ui-polish/`。


`frost-11` 继续增强材料效果：本地 `verifyagent-aurora.svg` 提供蓝紫 / 冰青柔和曲面背景，侧栏、流程卡、步骤条、主容器与快捷入口使用半透明多层填充、22–38px 背景模糊和白色边缘高光；`verifyagent-frost.svg` 提供细微磨砂纹理。辅助文字同步加深，移动端调整背景取景；降低透明度偏好与不支持 backdrop-filter 时有实底回退。本轮真实审批、复现、修复复验与证据 ZIP 流程回归通过，10 档宽度复核无横向溢出、页面错误或小于 14px 的可见文字，模型调用为 0。实际截图与材料计算值保存在忽略的 `.artifacts/ui-frost/`。

2026-10-30 的 `clear-12` 仅调整字体、文字颜色与字重：辅助小字从 14px 提高至 15px，普通文字最低 500 字重，主要按钮及输入内容为 16px，说明、占位提示、日志和结果详情同步加深。与修改前 CSS 逐项比较，所有非文字样式声明保持不变。只读浏览器检查覆盖 5 类页面、10 档宽度，共 50 个页面状态，无页面错误、横向溢出、低于 15px 或 500 字重的可见文字，也没有对文字及其祖先应用模糊或半透明；共享模型预算文件未变化。截图及核查记录位于忽略的 `.artifacts/ui-clear-type/`。
