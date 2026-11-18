# codex-remote-rp-duo

Retroid Pocket Duo 的双屏 Codex 遥控客户端。掌机通过 USB 或同一局域网连接 Mac，任务由 Mac 上已登录的 Codex 执行。

## 功能

- 上屏常驻「跟进」侧栏，可在置顶、运行中和完成未读的会话之间切换，并筛出待处理会话。
- 上屏查看流式回复、任务进度和折叠命令，按文件查看 diff。方向键和摇杆可滚动上屏。
- 下屏常驻键盘，可选择模型与推理强度，发送、停止和保留草稿。
- 搜索、续聊、置顶、重命名、归档及恢复 Mac 上的会话。
- 多个会话可同时运行，切换会话时原任务继续，停止只作用于当前会话。
- USB 初次配对，支持 TLS、Wi-Fi 重连和双屏／单屏切换。

## 截图

截图使用虚构会话和示例文件。

| 双屏对话与变更 | 下屏会话管理 |
| --- | --- |
| ![上屏显示示例对话及文件 diff，下屏显示输入框](docs/screenshots/dual-screen.png) | ![下屏展示示例会话列表与逐条操作菜单](docs/screenshots/sessions.png) |

## 从源码运行

需要 macOS、已登录的 Codex、Python 3.11+、JDK 21、Android Platform 36、Build Tools 36.0.0 和 `adb`。将 `ANDROID_HOME` 指向 SDK 根目录，并在掌机上启用 USB 调试。

```sh
./prepare-wifi.sh
./build-apk.sh
adb install -r DuoCodex.apk
./USB.command
```

首次配对后，同一局域网内可以拔掉 USB。用 `./USB.command --serve` 启动已配对的 Mac 服务，用 `./USB.command --stop` 停止。可用 `DUO_LAN_IP` 指定 Mac 的局域网 IPv4，或用 `DUO_USB_ONLY=1 ./USB.command` 只用 USB。新对话默认在 `.duo/workspace/`，也可在启动服务时传入工作目录。

上屏侧栏由 Mac 服务提供，升级 APK 后同时更新并重启 Mac 服务。

首次构建会在本机 `.duo/` 生成连接和签名材料。保留本机签名文件，后续才能覆盖安装自己的 APK。

```sh
python3 -m unittest discover -s tests -v
```
