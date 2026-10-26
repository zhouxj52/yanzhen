# 验真 Yanzhen VerifyAgent

**替用户独立验收软件：把原始需求锁定成标准，实际操作软件，用证据判断是否满足要求，并用原标准验证修复。**

例如页面提示“保存成功”，但刷新后数据丢失，验真会保留页面、接口和重新读取的证据，输出失败项与可复现步骤。最终呈现为浏览器工作台。

## 这轮做了什么

- 新增通用 Web/API 执行内核，不再要求每个场景先编写专用 adapter。支持 12 类受控动作和独立 HTTP/DOM 观测。
- 新增可追溯的契约、人工确认、不可覆盖的冻结版本和 SHA-256；验收由确定性断言计算。
- 接入 DeepSeek / Qwen 真实契约生成与逐步规划，模型错误明确记录，没有离线假响应。
- 从真实执行轨迹提取和删减复现，在新会话、目标支持的独立命名空间中重放并确认两次。
- 新增证据图、修复审计、外部候选部署复验、历史记录与可校验 ZIP。
- 保留原报销 / TodoMVC、原有 API、队列和 MCP 能力；现在提供 11 个 MCP 工具。前端聚焦开始验收与验收记录。

架构、验证命令、实际数据和未完成部分集中在 [开发与验收记录](docs/VerifyAgent开发与验收.md)。想先理解项目，看 [项目介绍](项目介绍.md)。

## 给贡献者的功能验收包

开源应用评测已收进单文件 [scripts/benchmark_upstream.py](scripts/benchmark_upstream.py)，包含固定版本来源、31 项业务检查、预期结果、准备步骤、目标启动、报告生成和证据核查。安装项目依赖、按文件头说明准备两个目标后，无需启动网页即可运行：

```powershell
.venv\Scripts\python.exe scripts\benchmark_upstream.py --help
.venv\Scripts\python.exe scripts\benchmark_upstream.py --list
.venv\Scripts\python.exe scripts\benchmark_upstream.py --check
.venv\Scripts\python.exe scripts\benchmark_upstream.py --approve-local-upstream-writes
.venv\Scripts\python.exe scripts\benchmark_upstream.py --audit
```

默认不调用模型，输出 `.artifacts/` 下的 Markdown、JSON 和逐条 ZIP 证据。预期为 **30 项正常要求 PASS + 1 项已知越权缺陷 FAIL**；退出码可用于 CI 判断结果是否符合预期。可选 `--allow-model` 另测真实规划，需要自行配置 API，沿用现有累计预算限制。它是选定功能的检查包，不能证明所有功能完整，也不是上游官方完整套件或通用自主验收成功率。演示剧场和开源实测展示页面已移除。

## 运行新的工作台

首次安装仍使用 `scripts/bootstrap.ps1`。已有本地环境时，分别打开两个 PowerShell 窗口：

```powershell
# 窗口 1：独立的、可丢弃的测试应用
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component target
```

```powershell
# 窗口 2：工作台，演示模式明确关闭模型调用
& D:/openjiuwen/scripts/start_verifyagent.ps1 -Component workbench -WithDemo
```

打开 [项目验收工作台](http://127.0.0.1:8767/static/verifyagent.html)，首页有两个入口：

- **验收我的项目**：先把项目运行起来，填本机或内网测试地址、粘贴具体验收要求。只读连接检查会说明地址未授权、服务未启动或需要登录等问题；当前不支持直接上传 ZIP / GitHub 源码并启动。
- **先体验一个示例**：载入已准备好的测试地址、清单与操作，不调用大模型。阅读中文清单并确认，再开始真实检查。

整个流程是 **接入项目 → 确认检查清单 → 实际执行 → 查看结果**。普通流程不用编辑 JSON；身份、手动配置、结构化标准与开发者复验工具均折叠在高级设置中。填写、点击、写接口仍须逐动作确认。

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

然后在工作台选择 DeepSeek。密钥只由后端读取，`.env` 已被 Git 忽略。成本账本在产物目录的 `verifyagent/model-budget.json`；保留它，重启不会清空累计预留。环境变量优先于 `.env`。

## 当前边界

本轮 87 项测试通过。真实 DeepSeek 及 JiuwenSwarm 受限规划运行时都已实际执行浏览器并发现持久化缺陷；页面执行时改名后，真实模型收到超时错误，改用新按钮并在原契约下通过。

只支持服务端白名单中的本地 / 私网测试地址；账号和 API 描述可由人提供。Swarm 当前负责单规划角色的请求 / 会话编排，总验收循环和工具由 VerifyAgent 控制。跨角色协作、新项目盲测和模型对照 / 消融实验仍未完成。系统支持已部署修复版本复验，没有自动修改业务源代码。

开源依赖与复用归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本轮修改保留在本地分支 `codex/verifyagent-core`，尚未推送。
