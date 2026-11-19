# 仓库文档参考

查阅日期：2026-11-19。

以下项目仅用于参考 README、安装指南、问题反馈和发布文档的组织方式；不表示本项目基于它们的代码，也不表示依赖、合作或官方背书。上游能力与授权条款不自动适用于本项目。

## OpenAI Codex

- [README](https://github.com/openai/codex/blob/main/README.md) 先说明产品定位、展示界面，再提供简短安装入口，并将完整文档、构建与贡献说明单独链接。
- [安装与构建文档](https://github.com/openai/codex/blob/main/docs/install.md) 将环境要求、源码构建和诊断日志分开说明。
- [贡献说明](https://github.com/openai/codex/blob/main/docs/contributing.md) 要求反馈包含复现步骤、预期与实际行为、版本、环境，以及脱敏后的日志。其“不接受外部代码 PR”是上游自己的维护政策，不作为本项目的默认政策。

适合本项目的做法：README 保留定位、双屏截图、主要功能与首次使用入口；详细构建、配置和排障分别成页。反馈模板明确 APK、Mac、Codex 组件、Android 版本与 USB/Wi-Fi 连接方式。

## scrcpy

- [README](https://github.com/Genymobile/scrcpy/blob/master/README.md) 明确 Android 前置条件、USB 调试要求和平台安装入口，并将连接、键盘、手柄等使用说明拆成独立文档；首页保留截图和常用操作。
- [Bug 模板](https://github.com/Genymobile/scrcpy/blob/master/.github/ISSUE_TEMPLATE/bug_report.md) 单独收集系统、软件版本、安装方式、设备型号、Android 版本和错误输出。
- [发布校验说明](https://github.com/Genymobile/scrcpy/blob/master/doc/verify-release.md) 区分校验和与签名验证，并给出各自的操作步骤。

适合本项目的做法：把 Retroid 双屏适配、macOS 主机和 USB 首次配对放在安装前置条件中；将首次安装与后续升级分开；发布时记录 APK 校验和及签名连续性，说明如何验证，避免把“有 SHA-256”描述成“具有独立签名证明”。

## Happy

- [README](https://github.com/slopus/happy/blob/main/README.md) 把产品能力、客户端下载和文档入口放在前面，再用组件表说明移动端、CLI、服务器与关联项目各自的职责。
- [开发与贡献说明](https://github.com/slopus/happy/blob/main/docs/CONTRIBUTING.md) 将开发环境与项目结构放在单独页面，要求变更说明聚焦问题，并提供真实运行的截图、录屏或日志作为验证依据。

适合本项目的做法：用一张简短结构图说明掌机 Android 客户端、Mac 桥接和 Codex app-server 的关系；贡献与发布检查记录实际验证步骤；截图统一保存在文档目录，使用示例会话和示例文件。

Happy 的商店分发、端到端加密和多用户协作属于它自己的产品能力。本项目只描述源码和实际验证支持的连接、配对及会话能力。

## 本项目的取舍

1. 首页优先回答“这是什么、适合谁、怎么开始”，详细操作通过文档链接展开。
2. 明确区分已配对设备升级和新 Mac 首次构建；不把针对已有配对环境生成的 APK 描述成通用安装包。
3. 反馈与 PR 模板收集可复现证据，避免提交真实会话、敏感目录、凭据和未脱敏日志。
4. 文档、验证结果和下载链接对应具体版本，测试通过、设备验证和发布成功分别记录。
5. 保持项目现有可见性与授权状态，不因为参考开源项目而自动添加许可证或宣称成为官方客户端。
