# 安装、配对与升级

[返回首页](../README.md)

## 先选择适用路径

| 场景 | 做法 |
| --- | --- |
| 第一次在自己的 Mac 使用 | 在这台 Mac 生成配对材料、构建 APK，再用 USB 首次配对。 |
| 已配对设备升级 | 保留原 CA 和签名，查看对应 Release 的升级说明，覆盖安装。 |
| 使用仓库现成 Release APK | 仅适用于其构建时的配对 CA 环境；其他 Mac 请自行构建。 |
| 更换 Mac、丢失 CA 或签名 | 见下文迁移说明，不能直接当作普通覆盖升级。 |

APK 只内嵌配对 CA 的公钥证书，不包含 Mac 的 CA 私钥、服务器私钥或配对 token。Android 通过本地配对连接 Mac，不需要在掌机浏览器登录 ChatGPT。

## 环境准备

### Mac

- 已登录并可正常运行的 Codex。
- Python 3.11+。桥接使用 Python 标准库，无需安装 pip 依赖。
- JDK 21。
- Android SDK Platform 36、Build Tools 36.0.0 和 Platform Tools（ADB）。
- OpenSSL，支持 `req -addext` 与 `verify -verify_ip`。系统自带版本不满足时可使用 Homebrew 的 `openssl@3`。

可以先通过 Android Studio 的 SDK Manager 安装上述 SDK 组件。若使用 Homebrew 安装命令行依赖：

```sh
brew install python openjdk@21 android-platform-tools openssl@3

export ANDROID_HOME="$HOME/Library/Android/sdk"
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$(brew --prefix openssl@3)/bin:$PATH"

python3 --version
javac -version
adb version
openssl version
```

SDK 不在默认位置时，将 `ANDROID_HOME` 改成实际目录。构建脚本也支持 `DUO_PLATFORM_JAR` 和 `DUO_BUILD_TOOLS` 分别指定 `android.jar` 与 Build Tools 目录。

脚本默认查找 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`；找不到时查找 PATH 中的 `codex`。可用 `DUO_CODEX_BIN` 指定组件，建议使用支持当前会话分页与提问协议的桌面版组件。

### 掌机

1. 在开发者选项中打开 USB 调试。
2. 用支持数据传输的 USB 线连接 Mac。
3. 掌机出现授权提示时，允许这台 Mac。
4. 运行 `adb devices`，设备状态应为 `device`，不是 `unauthorized` 或 `offline`。

同时连接多台 Android 时，先设置 `ANDROID_SERIAL`，再执行安装与配对命令。

## 首次构建与连接

在仓库根目录运行：

```sh
./prepare-wifi.sh
./build-apk.sh
adb install -r DuoCodex.apk
./USB.command
```

`prepare-wifi.sh` 生成这台 Mac 的本地 CA 与服务器证书；构建 APK 时会嵌入该 CA。`USB.command` 启动 Mac 桥接并通过 ADB 完成配对，随后打开掌机客户端。

默认新聊天的工作目录为 `.duo/workspace/`。也可以传入一个已存在的目录：

```sh
mkdir -p "$HOME/Projects/codex-workspace"
./USB.command "$HOME/Projects/codex-workspace"
```

使用 `DUO_DATA_DIR` 时，请指定绝对路径，上述运行数据改为保存在指定目录；首次生成证书、构建、启动和后续升级都应使用同一个值。

## USB 与 Wi-Fi

USB 首次配对时，脚本可同时记录 Mac 的局域网 IPv4。Mac 与掌机在同一局域网时，可以拔掉 USB 继续连接。

```sh
# 指定 Mac 的实际局域网 IPv4
DUO_LAN_IP=192.168.1.10 ./USB.command

# 只使用 USB
DUO_USB_ONLY=1 ./USB.command
```

示例 IP 需要替换为 Mac 的实际地址。默认尝试读取 `en0` 的 IPv4，取不到有效地址时使用 USB。

USB 通道使用 `127.0.0.1:38457` 的 ADB 反向转发；局域网监听指定私有 IPv4 的 `38458`。Wi-Fi 需要允许 macOS 防火墙接收该桥接的局域网连接。

## 已配对设备升级

1. 先等待客户端发起的运行任务完成，再停止桥接。
2. 保留原 `.duo/` 或 `DUO_DATA_DIR`，尤其是 `runtime/tls/` 和 `build/`。
3. 更新到需要的版本，阅读该版本的 Release 说明。
4. 若 Android 部分变更，用相同 CA 与签名重新构建、覆盖安装。
5. 若 Web、Python 桥接或协议变更，同步更新 Mac 端代码并重新启动。

例如，在已 clone 的仓库中更新到最新 `main`：

```sh
./USB.command --stop
git pull --ff-only
./prepare-wifi.sh
./build-apk.sh
adb install -r DuoCodex.apk
./USB.command
```

本地有未提交修改时，先处理好自己的工作，再同步。只升级原生主题的版本也应以 Release 说明为准；页面和会话逻辑来自 Mac，更新 APK 并不自动更新 Mac 代码。

## 更换 Mac 或配对材料

- **CA 变化**：需要用新 CA 重新构建 APK，再进行 USB 配对。
- **Mac IP 变化，但 CA 保留**：运行证书准备和配对流程以更新服务器证书及地址，通常无需因 IP 本身变化重建 APK。
- **签名变化**：Android 会拒绝覆盖安装。优先恢复原签名与密码；卸载后重装会清除掌机本地数据，不作为默认升级步骤。
- **迁移到另一台 Mac**：可以自行妥善迁移配对与签名材料，或重新生成并构建；不要将私钥和 token 上传到仓库或附件。

下载校验与签名检查见[发布说明](releasing.md)。
