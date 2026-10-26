# 上游依赖与复用范围

本项目自主编写验收契约、检查、报告、演示系统和工作台，未整仓复制调研中的测试 Agent 产品。

| 上游 | 用途 | 上游许可 |
| --- | --- | --- |
| https://github.com/fastapi/fastapi | 本地 API 服务 | MIT |
| https://github.com/encode/uvicorn | ASGI 服务 | BSD-3-Clause |
| https://github.com/encode/httpx | HTTP 调用 | BSD-3-Clause |
| https://github.com/pydantic/pydantic | 结构校验 | MIT |
| https://github.com/microsoft/playwright | 浏览器执行、截图和 trace | Apache-2.0 |
| https://github.com/modelcontextprotocol/python-sdk | stdio MCP 服务与联调 | MIT |
| https://github.com/pytest-dev/pytest | 自动化测试 | MIT |

精确安装版本和传递依赖见 requirements.lock。上游完整许可证随依赖分发包保留；发布包含第三方分发物的制品前，需按其实际 LICENSE/NOTICE 补齐分发声明。本文件不是对传递依赖的完整法律审查。

Qwen3-Coder、Qwen3-VL、UI-TARS 的权重均未打包；真实模型在使用者配置的推理服务运行。尚未引入 Midscene、browser-use、OpenHands SDK 或 TestZeus Hercules 代码。

JiuwenSwarm 的 YAML 配置格式根据官方 jiuwenswarm 0.2.3 wheel 核对。该 wheel 仅下载至忽略的 .cache 作为调研资料，没有作为项目运行依赖分发，也没有复制其业务代码。MCP 适配为本项目自行实现。

## TodoMVC 目标应用

新增复用 [tastejs/todomvc](https://github.com/tastejs/todomvc/tree/ff43b02e59dfa604386bb382034b2cd07c2bcd8a/examples/javascript-es6/src)，固定提交 ff43b02e59dfa604386bb382034b2cd07c2bcd8a，MIT。完整许可见 third_party/todomvc/LICENSE 及随应用打包的 yanzhen/web/todomvc/LICENSE。原始源文件、SHA-256 与来源见 third_party/todomvc/SOURCE.json。

服务副本只调整浏览器模块导入、移除 webpack HMR / CSS 包导入，配上本地展示 CSS。上游 Store / Model / Controller / View 业务逻辑保留；healthy 对照场景显式替换内存存储为 localStorage 并调整 ID 起点，此修改不是上游原版。TodoMVC 是外部开源示例，不是本项目原创业务应用，也不是完整企业系统。

自主实现范围是目标适配、冻结契约关联、证据冲突规则、独立环境删减与确认、受限执行计划审查及前端报告。

## 前端设计参考（来源）

- [shadcn/ui](https://github.com/shadcn-ui/ui)（MIT）：参考官方 [Dashboard / Sidebar blocks](https://ui.shadcn.com/blocks) 的侧栏、面包屑和卡片组织方式。
- [Ant Design](https://github.com/ant-design/ant-design)（MIT）：参考官方布局与数据展示规范，安排表格、筛选、状态和空页面反馈。

shadcn/ui 和 Ant Design 仅作设计参考，没有复制其组件源码、Logo 或整页模板，也没有安装其 React 组件包。

- [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react)（MIT，Copyright 2025 MAX ROVENSKY）：参考并改写独立背景光学层、SVG 位移滤镜与边缘高光的实现方式，适配为本项目无需 React 的 `yanzhen/web/liquid-glass.js` 和 `glass.css`。保留完整许可于 `third_party/liquid-glass-react/LICENSE`。圆角矩形的位移图、本地生命周期、响应式布局和 SVG 壁纸由本项目实现，没有使用上游的 base64 贴图、React 包或整页模板。
- [React Bits / Glass Surface](https://reactbits.dev/components/glass-surface)：调研玻璃表面与折射效果，未复制其组件源码或安装其包。其当前许可为 MIT + Commons Clause，不能简写为纯 MIT。
- [Apple / Meet Liquid Glass](https://developer.apple.com/videos/play/wwdc2025/219/)：参考导航层与内容层的层级、悬浮圆角控件及通透材质原则。本项目为网页近似实现，不包含 Apple 的原生材质或品牌素材。
