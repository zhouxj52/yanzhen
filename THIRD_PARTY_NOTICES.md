# 上游依赖与复用范围

工作台本地字体使用 [Noto Sans SC](https://github.com/google/fonts/tree/main/ofl/notosanssc)（SIL Open Font License 1.1），CSS 别名为 `Yanzhen Sans`。将完整可变字体从 TTF 转为 WOFF2，没有删减字形或修改字形设计，保留原内部名称。完整许可、上游 Git blob 标识及源文件/发布文件 SHA-256 随字体放在 `yanzhen/web/fonts/`。字体通过本机静态服务加载，不请求外部字体 CDN。

本项目自主编写验收契约、检查、报告、演示系统和工作台，未整仓复制调研中的测试 Agent 产品。

| 上游 | 用途 | 上游许可 |
| --- | --- | --- |
| https://github.com/fastapi/fastapi | 本地 API 服务 | MIT |
| https://github.com/encode/uvicorn | ASGI 服务 | BSD-3-Clause |
| https://github.com/encode/httpx | HTTP 调用 | BSD-3-Clause |
| https://github.com/encode/httpcore | 固定 TCP 目标 IP，同时保留域名、TLS 与 Cookie 的传输层 | BSD-3-Clause |
| https://github.com/openJiuwen-ai/agent-core | openJiuwen 官方 Workflow 编排，固定发布包 0.1.19.post2 | Apache-2.0 |
| https://github.com/Kronuz/esprima-python | ECMAScript 2017 语法树解析和变异前后语法校验，固定 4.0.1；不执行目标脚本 | BSD-2-Clause |
| https://github.com/pydantic/pydantic | 结构校验 | MIT |
| https://github.com/microsoft/playwright | 浏览器执行、截图和 trace | Apache-2.0 |
| https://github.com/modelcontextprotocol/python-sdk | stdio MCP 服务与联调 | MIT |
| https://github.com/pytest-dev/pytest | 自动化测试 | MIT |

精确安装版本和传递依赖见 requirements.lock。上游完整许可证随依赖分发包保留；发布包含第三方分发物的制品前，需按其实际 LICENSE/NOTICE 补齐分发声明。本文件不是对传递依赖的完整法律审查。

Qwen3-Coder、Qwen3-VL、UI-TARS 的权重均未打包；真实模型在使用者配置的推理服务运行。尚未引入 Midscene、browser-use、OpenHands SDK 或 TestZeus Hercules 代码。

新增可选依赖 [JiuwenSwarm 0.2.3](https://github.com/openJiuwen-ai/jiuwenswarm)（Apache-2.0）。E2A 桥接使用其实际发布的 `E2AEnvelope` 和 `parse_agent_server_wire_chunk`，传输层由本项目编写。实际运行时使用官方 `JiuWenSwarm` facade、会话队列与历史，通过官方 `AgentAdapter` 协议接入本项目无原生工具的计量 JSON 规划适配器；固定版本的 `_ensure_adapter` 受保护扩展点需要随 SDK 升级复核。真实模型浏览器流程已运行，独立研究环境安装在忽略的 D 盘 `.cache/swarm-runtime`。未复制其业务源码，没有声明已完成跨角色多 Agent 协作。MCP 适配由本项目自行实现。

## 独立开源应用评测

2026-10-26 新增两个外部目标：

- [Spring Petclinic](https://github.com/spring-projects/spring-petclinic/tree/500158f732419217507c7656904b8e6aa1bcc0d6)，固定提交 `500158f732419217507c7656904b8e6aa1bcc0d6`，Apache-2.0。仅在忽略的 D 盘缓存中克隆和构建，未打包到验真发布物；上游 LICENSE/NOTICE 保留。人工根据其控制器测试、模型约束和模板编写外部验收协议，没有把上游 JUnit 全套测试计为验真实测。
- [OWASP Juice Shop](https://github.com/juice-shop/juice-shop/releases/tag/v20.3.0)，官方 `v20.3.0` Windows/Node24 发布包，MIT。发布包 SHA-256、固定版本、用例与使用范围集中在 `scripts/benchmark_upstream.py`。仅在忽略的 D 盘缓存中运行，未复制其业务实现；启动预加载脚本只限制环回监听。权限缺陷是上游有意保留的已知挑战，不是本项目原创漏洞发现。

RealWorld、BrowserGym、WebArena、MiniWoB++ 本轮仅作调研，未复用源码或声明已运行。调研不能替代各仓库及具体分发物的实际许可审查。

## TodoMVC 目标应用

新增复用 [tastejs/todomvc](https://github.com/tastejs/todomvc/tree/ff43b02e59dfa604386bb382034b2cd07c2bcd8a/examples/javascript-es6/src)，固定提交 ff43b02e59dfa604386bb382034b2cd07c2bcd8a，MIT。完整许可见 third_party/todomvc/LICENSE 及随应用打包的 yanzhen/web/todomvc/LICENSE。原始源文件、SHA-256 与来源见 third_party/todomvc/SOURCE.json。

服务副本只调整浏览器模块导入、移除 webpack HMR / CSS 包导入，配上本地展示 CSS。上游 Store / Model / Controller / View 业务逻辑保留；healthy 对照场景显式替换内存存储为 localStorage 并调整 ID 起点，此修改不是上游原版。TodoMVC 是外部开源示例，不是本项目原创业务应用，也不是完整企业系统。

自主实现范围是目标适配、冻结契约关联、证据冲突规则、独立环境删减与确认、受限执行计划审查及前端报告。

## 2026-10-28 扩展评测来源

- [bradtraversy/vanillawebprojects](https://github.com/bradtraversy/vanillawebprojects/tree/adc66a181a67049fb413c8862181ddc6c45ba22b)：固定提交 `adc66a181a67049fb413c8862181ddc6c45ba22b`，仅下载 Expense Tracker、Form Validator 及仓库说明到忽略的 D 盘缓存，未修改业务源码。所选仓库未声明许可证，记录为 `NOASSERTION`；业务源码不随验真分发，只发布来源、文件哈希及自主编写的验收协议。表单分支问题由本地审阅和独立原始浏览器步骤确认，不代表上游维护者确认。
- [MDN learning-area](https://github.com/mdn/learning-area/tree/21973263ba859ff3477919087b488157f9d618a6)：固定提交 `21973263ba859ff3477919087b488157f9d618a6`，CC0-1.0。下载完成版 `shopping-list-finished.html` 与 LICENSE 到忽略缓存；没有把教学空白模板当作完成项目。原业务源码未改动，新增评测仅检查选定的清单增删及字面文本行为。

新增文件的 SHA-256、Git blob 和固定提交见 `benchmarks/upstream-sources.json`。静态测试服务仅提供清单文件，并通过响应头限制外部连接；该限制不修改源码。Petclinic 与 Juice Shop 继续使用上文固定版本；5 个应用来自 4 个仓库。新增结果不计入官方完整套件成绩或陌生项目自主成功率。

## 前端设计参考（来源）

- [shadcn/ui](https://github.com/shadcn-ui/ui)（MIT）：参考官方 [Dashboard / Sidebar blocks](https://ui.shadcn.com/blocks) 的侧栏、面包屑和卡片组织方式。
- [Ant Design](https://github.com/ant-design/ant-design)（MIT）：参考官方布局与数据展示规范，安排表格、筛选、状态和空页面反馈。

shadcn/ui 和 Ant Design 仅作设计参考，没有复制其组件源码、Logo 或整页模板，也没有安装其 React 组件包。

- [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react)（MIT，Copyright 2025 MAX ROVENSKY）：参考并改写独立背景光学层、SVG 位移滤镜与边缘高光的实现方式，适配为本项目无需 React 的 `yanzhen/web/liquid-glass.js` 和 `glass.css`。保留完整许可于 `third_party/liquid-glass-react/LICENSE`。圆角矩形的位移图、本地生命周期、响应式布局和 SVG 壁纸由本项目实现，没有使用上游的 base64 贴图、React 包或整页模板。
- [React Bits / Glass Surface](https://reactbits.dev/components/glass-surface)：调研玻璃表面与折射效果，未复制其组件源码或安装其包。其当前许可为 MIT + Commons Clause，不能简写为纯 MIT。
- [Apple / Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/)：参考导航层与内容层的层级、悬浮圆角控件及通透材质原则。本项目为网页近似实现，不包含 Apple 的原生材质或品牌素材。
