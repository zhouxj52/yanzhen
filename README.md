# 验真 Yanzhen VerifyAgent

**替用户独立验收软件：把原始需求锁定成标准，实际操作软件，用证据判断是否满足要求，并用原标准验证修复。**

例如页面提示“保存成功”，但刷新后数据丢失，验真会保留页面、接口和重新读取的证据，输出失败项与可复现步骤。最终呈现为浏览器工作台。

## 这轮做了什么

- 新增通用 Web/API 执行内核，不再要求每个场景先编写专用 adapter。支持 12 类受控动作和独立 HTTP/DOM 观测。
- 新增可追溯的契约、人工确认、不可覆盖的冻结版本和 SHA-256；验收由确定性断言计算。
- 优先通过 openJiuwen 官方 Workflow 编排需求分析与逐步规划，底层可选 DeepSeek / Qwen；共享真实调用预算，模型错误不会变成离线假响应。
- 新增 GitHub、ZIP、本地目录源码接入和静态预检；纯静态 HTML 可直接预览，Web / API 也可连接已授权的公网测试部署。
- 从真实执行轨迹提取和删减复现，在新会话、目标支持的独立命名空间中重放并确认两次。
- 新增证据图、修复审计、外部候选部署复验、历史记录与可校验 ZIP。
- 保留原报销 / TodoMVC、原有 API、队列和 MCP 能力；现在提供 11 个 MCP 工具。前端聚焦开始验收与验收记录。

架构、验证命令、实际数据和未完成部分集中在 [开发与验收记录](docs/VerifyAgent开发与验收.md)。想先理解项目，看 [项目介绍](项目介绍.md)。

## 新增：反例挑战与角色协作

首页选择 **先体验一个示例 → 这套验收，能识破假保存吗？**。先审阅并冻结人工清单，实际完成正常项目验收；通过后，在结果中展开“反例挑战”，查找候选、准备补丁、确认隔离副本操作，再启动。默认重放已执行的真实轨迹，模型调用为 0。

反例来自实际源码语法树：移除 `localStorage/sessionStorage.setItem`、移动比较边界、反转相等条件。每份副本只应用一个准确补丁，原文件和冻结标准保持不变；正常对照与变异目标匿名随机排序。执行端不接收补丁、标签或源码引用。开始前公开分配哈希，结束后揭晓随机 nonce 与分配并核对完整性，下载包含逐次运行 ZIP、补丁、源码清单和冻结契约。

存活候选可能与当前要求无关、等价或未被当前操作覆盖，不能直接叫漏检；正常对照不通过时不计算检出比例。受阻、待澄清和未执行项单独显示。

高级验收方式新增 **openJiuwen · 多角色协作执行**：冻结后由需求分析、反例挑战、执行规划三个模型角色和确定性证据审查角色依次交接。角色只引用已有冻结探针，不能修改标准；审查发现必须操作缺失时要求执行者补证。相同运行中的已验证分析可复用，所有角色共享本次模型次数限制及持久费用账本。

挑战还支持单角色与多角色对照：每次运行相同模型请求 / 时间上限，在新浏览器上下文中操作相同变异，结果只在共同完成的变异上比较。相同请求上限不等于相同实际费用。本轮对照只跑过显式模型传输替身 + 真实 SDK/浏览器工具，未宣称真实模型多角色优于单角色。

```powershell
# 默认人工轨迹，不调用模型
.venv/Scripts/python.exe scripts/check_counterexample_ui.py
```

首版限定可直接预览的 HTML/JavaScript、ECMAScript 2017 和单项冻结契约；不执行任意后端源码或安装脚本。真实模型已完成 1 个正常对照 + 1 个存储写入变异：正常通过、变异失败，14 次真实模型请求。累计保守费用预留 4.758062 元，仍在已授权的 5 元内；经用户允许，本次次数上限从 60 调整为 100。公开数据见 `benchmarks/results/counterexample-collaboration.json`，它是受控样例，不是陌生项目盲测成绩。

## 给贡献者的功能验收包

开源应用评测集中在 [scripts/benchmark_upstream.py](scripts/benchmark_upstream.py)，默认覆盖 **4 个上游仓库、5 个应用、49 条检查**：Petclinic 22、Juice Shop 9、Expense Tracker 7、Form Validator 7、MDN Shopping List 4。静态源码的固定提交、文件哈希与许可状态见 [来源清单](benchmarks/upstream-sources.json)，实际结果见 [本轮记录](benchmarks/results/upstream-fixed-plans-v3.json)。安装项目依赖、按文件头说明准备目标后，无需启动工作台即可运行：

```powershell
.venv\Scripts\python.exe scripts\benchmark_upstream.py --help
.venv\Scripts\python.exe scripts\benchmark_upstream.py --list
.venv\Scripts\python.exe scripts\benchmark_upstream.py --prepare
# 分别在三个终端启动 --serve petclinic、--serve juice-shop、--serve static
.venv\Scripts\python.exe scripts\benchmark_upstream.py --check
.venv\Scripts\python.exe scripts\benchmark_upstream.py --approve-local-upstream-writes
.venv\Scripts\python.exe scripts\benchmark_upstream.py --audit
```

本轮实际执行 **43 项正常检查 PASS，6 条缺陷用例 FAIL，与预注册结果 49/49 一致**，模型请求为 0；6 条缺陷用例属于 2 个缺陷组，不能说成发现 6 个独立漏洞。表单分支问题经本地源码审阅和另一套原始浏览器步骤确认，Juice Shop 则是上游已知挑战。报告保留异常、受阻、分母、耗时与费用；所有契约、预期标签和动作先落盘并公开本地协议哈希，再执行验收。小数金额假设导致的一次试跑失败保留，修订协议不与旧结果合并。

输出位于 `.artifacts/upstream-evaluations/本次编号/`，包含 HTML/JSON、预注册协议、独立参考截图以及逐条证据组成的 `evaluation.zip`，可离线核对哈希。旧 31 条协议使用 `--suite legacy`；该模式的 `--allow-model` 可另测两项真实规划，沿用本地累计预算，脚本不覆盖限额。上述结果衡量选定业务的固定流程集成能力；陌生项目盲测、独立人工标注和真实模型对照仍待完成。演示剧场和开源实测导航保持移除。

## 需求与证据如何对应

确认清单前可展开“检查清单是否遗漏了需求？”，结果页新增 **需求 → 检查 → 执行 → 证据**：逐条保留原始需求，查看冻结检查、该检查所在流程的实际步骤、截图和断言直接使用的观测。支持筛选未覆盖/部分未关联、问题/受阻/待澄清，刷新后可回到同一记录；关联数据同时写入证据 ZIP 的 `requirement-coverage.json`。

关联来自原文精确引用，不能把文字被引用等同于语义完整覆盖。没有结果检查、只关联前置条件、重复引用无法定位、缺少必要操作或证据哈希不一致，都不会计为已验证。可运行 `scripts/check_requirement_coverage_ui.py` 验证真实失败与未覆盖需求同时显示，不调用模型。

## 运行新的工作台

首次安装使用 `scripts/bootstrap.ps1`，默认安装固定版本 openJiuwen；仅需离线内核时可加 `-CoreOnly`。已有本地环境时，分别打开两个 PowerShell 窗口：

```powershell
# 窗口 1：独立的、可丢弃的测试应用
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component target
```

```powershell
# 窗口 2：工作台，演示模式明确关闭模型调用
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component workbench -WithDemo
```

打开 [项目验收工作台](http://127.0.0.1:8767/static/verifyagent.html)，首页有两个入口：

- **验收我的项目**：选择运行地址、公开 GitHub、ZIP 或本地目录。源码会生成哈希快照与静态预检报告；纯静态 HTML 可以一键启动预览。需要构建或后端的项目，按 README 启动后关联地址，再填写具体验收要求。已运行目标支持本机、内网及授权公网测试部署。
- **先体验一个示例**：载入已准备好的测试地址、清单与操作，不调用大模型。阅读中文清单并确认，再开始真实检查。

整个流程是 **接入项目 → 确认检查清单 → 实际执行 → 查看结果**。源码入口的真实浏览器回归可运行 `.venv/Scripts/python.exe scripts/check_project_intake_ui.py`；增加 `--with-github` 验证公开仓库在线导入。该脚本只对自己创建的静态测试样例使用人工清单，不调用模型。普通流程不用编辑 JSON；身份、手动配置、结构化标准与开发者复验工具均折叠在高级设置中。填写、点击、写接口仍须逐动作确认。

工作台 `clear-12` 使用独立的本地样式与 SVG 图标，以蓝紫 / 冰青曲面背景衬托半透明磨砂卡片、玻璃导航及白色边缘高光。保留磨砂材料参数，文字统一使用深色、至少 500 字重和 15px 字号，主要按钮及输入内容为 16px。首页四种材料可直接选择；验收完成后默认收起执行过程，目标地址和标准版本仍显示，实际结果以统计与观测 / 标准对照呈现。需求关联、报告下载与开发者复验继续保留，验收记录支持本地搜索。

两个命令都在前台运行，Ctrl+C 关闭。Windows 下工作台不要加 uvicorn `--reload`，否则浏览器子进程可能不可用。产物在 D 盘 `.artifacts/verifyagent-service`，不会覆盖旧端口的服务。旧版演示仍可使用 `scripts/demo.ps1`，默认端口 8765。

## 在哪里配置 API key

在项目根目录 **`D:\openjiuwen\.env`** 填写以下字段；不要把密钥贴到网页或聊天中。

```dotenv
YZ_DEEPSEEK_BASE_URL=https://api.deepseek.com
YZ_DEEPSEEK_MODEL=deepseek-flash
YZ_DEEPSEEK_API_KEY=你的密钥

# 本轮授权的 5 元验证上限；预留按保守上界累计，不是实际账单
YZ_VERIFY_BUDGET_CNY=5
YZ_VERIFY_PRICED_MODEL=deepseek-flash
YZ_VERIFY_INPUT_CNY_PER_MILLION=2
YZ_VERIFY_OUTPUT_CNY_PER_MILLION=8
YZ_VERIFY_MAX_PAID_CALLS=60
```

价格配置依据 [DeepSeek 官方定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，核对日期 2026-10-26。更换模型或价格时需重新核对；实际账单以提供方为准。

明确启用真实 API 后启动：

```powershell
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component workbench -WithDemo -EnableModel
```

安装竞赛运行时后，工作台优先选择 **openJiuwen**，它通过下方配置使用 DeepSeek：

```powershell
# uv 缓存、临时目录均放在 D 盘
$env:UV_CACHE_DIR='D:/openjiuwen/.cache/uv'
$env:TEMP='D:/openjiuwen/.tmp'
$env:TMP=$env:TEMP
uv pip install --python .venv/Scripts/python.exe ".[openjiuwen]"
```

```dotenv
YZ_VERIFY_DEFAULT_PLANNER=openjiuwen
YZ_OPENJIUWEN_MODEL_PROVIDER=deepseek
# 精确来源用逗号分隔；公网应填写自己获授权的测试部署
YZ_VERIFY_ALLOWED_ORIGINS=http://127.0.0.1:8771,https://your-staging.example.com
# 允许读取的服务器目录用分号分隔
YZ_PROJECT_ALLOWED_ROOTS=D:/openjiuwen;D:/projects
```

openJiuwen 是 Agent 框架，API key 属于底层模型供应商。固定 SDK `openjiuwen==0.1.19.post2`；实际执行 request → model_planning → schema_validation → return 四个节点，无自动重试、无原生 Shell / 文件工具。批准、工具执行与冻结断言由独立内核控制，运行中保留节点时间与工作流 ID，不声称完整 Swarm 多角色协作。

密钥只由后端读取，`.env` 已被 Git 忽略。成本账本在产物目录的 `verifyagent/model-budget.json`；保留它，重启不会清空累计预留。环境变量优先于 `.env`。

## 当前边界

本轮 129 项测试通过，覆盖源码接入、真实 HTTP/浏览器、TLS 域名与 Cookie、反例分配承诺、原源码保护、官方 openJiuwen 多角色路由、共享调用上限与审查补证。模型传输单元测试使用显式 Mock；另有已记录的真实模型链路联调和上文的角色协作受控验收。真实 DeepSeek 及 JiuwenSwarm 受限规划运行时都已实际执行浏览器并发现持久化缺陷；页面执行时改名后，真实模型收到超时错误，改用新按钮并在原契约下通过。

支持服务端白名单中的本地 / 私网 / 公网测试地址；公网 DNS 只接受全公共 IP 并固定连接 IP，保留 HTTPS 证书验证。账号和 API 描述可由人提供。原 JiuwenSwarm 接口仍负责受限单规划角色；新增 openJiuwen Workflow 多角色执行，总验收循环与工具继续由 VerifyAgent 控制。陌生项目盲测、真实模型单角色 / 多角色效果对照及完整消融实验仍未完成。系统支持已部署修复版本复验，没有自动修改业务源代码。

开源依赖与复用归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。当前分支包含源码接入、公网目标连接及 openJiuwen 优先编排的扩展。

源码接入只做结构、配置和 Python 静态语法预检，不会运行不明安装或启动脚本，也不等于完成业务验收。私有 GitHub 仓库、自动构建动态项目、桌面 / 移动原生应用暂未支持；源码与运行部署的关联由用户声明，尚未证明部署产物来自该源码。静态预览只支持站内资源，外部 CDN 会被拦截。
