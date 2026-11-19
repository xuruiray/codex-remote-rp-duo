# 架构与开发

[返回首页](../README.md)

## 组件职责

| 位置 | 职责 |
| --- | --- |
| `android/src/com/xurui/duocodex/` | Activity、双屏发现、可信 WebView、键盘、原生输入框、手柄和退出。 |
| `android/res/` | 图标、原生主题、网络信任配置。 |
| `bridge.py` / `bridge_http.py` | 启动 HTTPS 服务，提供静态界面和鉴权 API。 |
| `app_server.py` | Codex app-server 子进程和逐行 JSON-RPC 传输。 |
| `codex_session.py` | 会话选择、独立任务状态、历史分页与调度。 |
| `questions.py` | 问题归一化、答案校验、请求生命周期和公开状态。 |
| `session_messages.py` / `change_set.py` | 消息转换、图片读取和本轮文件 diff。 |
| `web/` | 会话导航、输入、对话渲染、提问与变更面板。 |
| `tests/` | 使用模拟协议组件的 Python 回归，不需要真实账号或 API Key。 |
| `USB.command` / `prepare-wifi.sh` / `build-apk.sh` | 本地配对、证书准备和手动 Android 构建。 |

Android 使用 Java + WebView，Mac 桥接使用 Python 标准库，Web 为原生 JavaScript 模块与 CSS。当前没有 Gradle、Node 包管理器或独立前端构建步骤。

## 本地检查

在仓库根目录执行：

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check-docs.py
bash -n USB.command prepare-wifi.sh build-apk.sh

for file in web/*.js; do
  node --input-type=module --check < "$file"
done

git diff --check
```

JavaScript 语法检查使用 Node.js 22。桥接当前的 Python 回归覆盖 RPC 断开、历史去重与分页、并行任务、提问回传、过期答案以及冷会话选择竞争；通过这些检查不代表已经完成 Android 真机验证。

## Android 构建

按[安装指南](installation.md)准备 JDK、SDK 和本机配对材料后：

```sh
./build-apk.sh
adb install -r DuoCodex.apk
```

构建脚本使用 aapt2、javac、d8、zipalign 和 apksigner，输出仓库根目录的 `DuoCodex.apk`。构建时嵌入本机配对 CA 公钥证书；签名材料保存在本地数据目录，不能随源码提交。

修改 Web 或 Python 代码时，也要将 Mac 桥接运行目录更新为同一份代码；Web 页面由桥接实际提供，不是打包进 APK 的静态页面。

## 关键约束

- 会话和停止请求必须核对原会话/turn，晚到的加载结果不能覆盖更新的选择。
- 提问答案绑定原会话和请求；重复提交、请求已结束和取消都应有确定结果。
- RPC 读取线程不能等待用户作答，否则其他通知与会话会被阻塞。
- 下屏保持输入焦点，模型、推理强度和原生编辑弹窗结束后恢复键盘。
- 保密输入不进入公开状态或掌机本地草稿。
- 不把不存在的模型、强度或桌面工具能力写进 UI。

## 真机回归

涉及双屏、输入或交互的变更，至少记录以下实际验证结果：

1. 上屏全屏、会话栏展开/收起、触屏和手柄滚动。
2. 下屏键盘常驻，模型/推理菜单选择与取消，以及原生输入弹窗结束后的恢复。
3. 会话切换、慢会话切走/新建、并行任务与当前任务停止。
4. 普通消息、历史上滑加载、命令折叠和逐文件 diff。
5. AI 提问的点选、自由回答、取消、过期答案与跨会话保护。
6. 双击返回退出，以及 USB/Wi-Fi 恢复后的会话与草稿。

只报告实际执行过的场景；模拟组件验证、真实 Codex 验证与掌机验证分别说明。

## 截图维护

文档截图放在 `docs/screenshots/`。使用真实客户端、虚构会话和示例文件拍摄，检查原始图片再提交；不要上传真实项目目录、工作会话、用户消息、通知、配对参数或终端密钥。

当前首页截图的用途是展示布局和操作，不表示截图中的示例文件是仓库源码，也不承诺所有账号拥有同一模型列表。
