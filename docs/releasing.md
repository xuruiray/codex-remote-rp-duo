# 版本发布与下载校验

[返回首页](../README.md) · [GitHub Releases](https://github.com/xuruiray/codex-remote-rp-duo/releases)

## 下载与校验

源码和 Release 均可公开访问，可直接从 [GitHub Releases](https://github.com/xuruiray/codex-remote-rp-duo/releases) 下载附件。现成 APK 适用于构建时的配对 CA 环境；首次在自己的 Mac 使用应按[安装指南](installation.md)自行构建。

使用 GitHub CLI 下载最新 Release 的 APK 和校验文件：

```sh
gh release download --repo xuruiray/codex-remote-rp-duo \
  --pattern '*.apk' --pattern 'SHA256SUMS' --dir release-downloads

cd release-downloads
shasum -a 256 -c SHA256SUMS
```

`SHA256SUMS` 从 v0.1.24 起提供，较早 Release 不保证有该附件。校验和用于核对下载文件是否与发布资产一致，不是独立的发布者签名证明。

需要核对 Android 签名时，使用 SDK 中的 apksigner：

```sh
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --print-certs your-release.apk
```

覆盖升级必须保持原签名身份。可以与自己先前保留的可信 APK 比较证书指纹；不要用更换签名后的卸载重装来代替连续性检查。

## 发布前

1. 明确源码提交和版本范围，更新 AndroidManifest 的 versionName/versionCode，以及对应版本记录。
2. 执行[本地检查](development.md#本地检查)，查看 CI 结果；涉及 Android 或交互时完成适用的真机回归。
3. 保留正确的配对 CA 与原签名，运行 `./build-apk.sh`。
4. 在目标掌机覆盖安装候选 APK，记录实际安装版本、签名、SHA-256 和实际验证场景。
5. 使用示例内容拍摄截图，检查待提交文件，不混入运行数据、私钥、工作日志或真实会话。

CI 不持有维护者的配对和签名材料，也不会自动生成可供现有掌机覆盖安装的正式 APK。

## 准备资产

以下以未来版本号作示例，需要替换为实际版本：

```sh
version=0.1.25
mkdir -p release-assets
cp DuoCodex.apk "release-assets/codex-remote-rp-duo-v${version}.apk"
(
  cd release-assets
  shasum -a 256 "codex-remote-rp-duo-v${version}.apk" > SHA256SUMS
)
```

`release-assets/` 和 APK 不加入源码提交。Release 应包含：

- 对应版本的 APK。
- 对应 APK 的 `SHA256SUMS`。
- 简洁的变更说明、已执行的验证、是否需要同步更新并重启 Mac 桥接。

## 发布与回读

将审核后的变更提交并推送到 main，记录完整提交 SHA，再创建指向该提交的 Release。发布后重新下载资产校验 SHA-256，核对 tag、源码提交和实际安装候选一致。

文档、模板和仓库配置更新可以直接提交 main，不必为没有 APK 变化的内容创建新的 Android 版本。
