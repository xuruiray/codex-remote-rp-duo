#!/usr/bin/env bash
set -euo pipefail
umask 077
base=$(cd "$(dirname "$0")" && pwd)
data=${DUO_DATA_DIR:-"$base/.duo"}
state="$data/build"
sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}
platform=${DUO_PLATFORM_JAR:-"$sdk/platforms/android-36/android.jar"}
tools=${DUO_BUILD_TOOLS:-"$sdk/build-tools/36.0.0"}
[[ -f $platform && -x $tools/aapt2 && -x $tools/d8 && -x $tools/zipalign && -x $tools/apksigner ]] || {
  echo "请配置 ANDROID_HOME 并安装 Android SDK Platform 36 和 Build Tools 36.0.0。"
  exit 1
}
mkdir -p "$state"
build=$(mktemp -d "$state/build.XXXXXX")
trap 'rm -rf "$build"' EXIT
mkdir -p "$build/classes" "$build/dex"
res="$build/res"
mkdir -p "$res"
cp -R "$base/android/res/." "$res/"
tls="$data/runtime/tls"
[[ -s $tls/ca.crt ]] || { echo "请先运行 prepare-wifi.sh"; exit 1; }
mkdir -p "$res/raw"
cp "$tls/ca.crt" "$res/raw/duo_lan_ca.pem"
password="$state/signing-password"
if [[ ! -s $password && -f $state/local.keystore ]]; then
  echo "找不到本地签名密码文件。请恢复原签名文件和密码后再构建。"
  exit 1
fi
if [[ ! -s $password ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$password"
fi
if [[ ! -f $state/local.keystore ]]; then
  keytool -genkeypair -keyalg RSA -keysize 2048 -validity 10000 \
    -dname 'CN=Duo Codex local build' -keystore "$state/local.keystore" \
    -storepass:file "$password" -alias duo-codex
fi
"$tools/aapt2" compile --dir "$res" -o "$build/resources.zip"
"$tools/aapt2" link -I "$platform" --manifest "$base/android/AndroidManifest.xml" \
  -o "$build/unsigned.apk" "$build/resources.zip"
javac --release 11 -classpath "$platform" -d "$build/classes" \
  "$base"/android/src/com/xurui/duocodex/*.java
jar --create --file "$build/classes.jar" -C "$build/classes" .
"$tools/d8" --min-api 29 --lib "$platform" --output "$build/dex" "$build/classes.jar"
(cd "$build/dex" && zip -q "$build/unsigned.apk" classes.dex)
"$tools/zipalign" -f 4 "$build/unsigned.apk" "$build/aligned.apk"
"$tools/apksigner" sign --v4-signing-enabled false --ks "$state/local.keystore" --ks-pass "file:$password" \
  --out "$build/DuoCodex.apk" "$build/aligned.apk"
"$tools/apksigner" verify "$build/DuoCodex.apk"
mv "$build/DuoCodex.apk" "$base/DuoCodex.apk"
