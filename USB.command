#!/usr/bin/env bash
set -euo pipefail
umask 077
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
base=$(cd "$(dirname "$0")" && pwd)
data=${DUO_DATA_DIR:-"$base/.duo"}
state="$data/runtime"
default_workspace="$data/workspace"
mkdir -p "$state" "$default_workspace"
label="com.xurui.duocodex.bridge.38457"
adb_device=(adb)
if [[ -n ${ANDROID_SERIAL:-} ]]; then adb_device+=( -s "$ANDROID_SERIAL" ); fi
if [[ "${1:-}" == "--stop" ]]; then
  launchctl remove "$label" 2>/dev/null || true
  for ((attempt=0; attempt<20; attempt++)); do
    if ! launchctl list "$label" >/dev/null 2>&1 && ! nc -z 127.0.0.1 38457 2>/dev/null; then break; fi
    sleep .2
  done
  "${adb_device[@]}" reverse --remove tcp:38457 2>/dev/null || true
  printf '%s\n' "USB 连接已关闭。"
  exit
fi
pair=1
if [[ "${1:-}" == "--serve" ]]; then pair=0; shift; fi
workspace=$(cd "${1:-$default_workspace}" && pwd)
if [[ $pair == 1 ]]; then "${adb_device[@]}" get-state >/dev/null; fi
codex_bin=${DUO_CODEX_BIN:-"/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"}
if [[ ! -x $codex_bin ]]; then codex_bin=$(command -v codex); fi
if [[ ! -s "$state/token" ]]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(36))' > "$state/token"
fi
token=$(cat "$state/token")
tls="$state/tls"
[[ -s $tls/ca.crt && -s $tls/server.crt && -s $tls/server.key ]] ||
  { echo "请先运行 prepare-wifi.sh 并编译 Codex。"; exit 1; }
lan_ip=""
lan_args=()
if [[ ${DUO_USB_ONLY:-0} != 1 ]]; then
  lan_ip=${DUO_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}
  if [[ -n $lan_ip ]] && python3 -c 'import ipaddress, sys; ip = ipaddress.IPv4Address(sys.argv[1]); sys.exit(not (ip.is_private and not ip.is_loopback))' "$lan_ip"; then
    "$base/prepare-wifi.sh" "$lan_ip" >/dev/null
    lan_args=(--lan-ip "$lan_ip")
  else
    lan_ip=""
  fi
fi
ready() {
  curl -fsS --max-time 2 --cacert "$tls/ca.crt" --header "Authorization: Bearer $token" \
    https://127.0.0.1:38457/api/state 2>/dev/null | python3 -c 'import json, sys; sys.exit(not json.load(sys.stdin)["connected"])' 2>/dev/null
}
if ready; then
  if [[ "$workspace" != "$(cat "$state/workspace")" ]]; then
    printf '%s\n' "工作目录已在使用中。请运行 USB.command --stop，再指定新的目录。" >&2
    exit 1
  fi
  if [[ "$lan_ip" != "$(cat "$state/lan" 2>/dev/null || true)" ]]; then
    printf '%s\n' "连接模式已变更。请运行 USB.command --stop，再启动新连接。" >&2
    exit 1
  fi
else
  printf '%s\n' "$workspace" > "$state/workspace"
  printf '%s\n' "$lan_ip" > "$state/lan"
  launchctl remove "$label" 2>/dev/null || true
  : > "$state/bridge.log"
  launchctl submit -l "$label" -o "$state/bridge.log" -e "$state/bridge.log" -- \
    /usr/bin/env "PATH=$PATH" "$(command -v python3)" "$base/bridge.py" \
    --workspace "$workspace" --token-file "$state/token" --session-file "$state/session.json" --codex "$codex_bin" \
    --tls-cert "$tls/server.crt" --tls-key "$tls/server.key" \
    ${lan_args[@]+"${lan_args[@]}"}
  for ((attempt=0; attempt<30; attempt++)); do
    if ready; then break; fi
    sleep .4
  done
  if ! ready; then
    printf '%s\n' "连接启动失败，日志位于 $state/bridge.log" >&2
    exit 1
  fi
fi
if [[ $pair == 1 ]]; then
  "${adb_device[@]}" reverse tcp:38457 tcp:38457 >/dev/null
  "${adb_device[@]}" shell am start -S --display 0 -n com.xurui.duocodex/.PairActivity \
    --es pairing_token "$token" --es lan_host "${lan_ip:-disabled}" >/dev/null
fi
printf '%s\n' "Codex 服务已启动，工作目录 $workspace"
if [[ -n $lan_ip ]]; then printf '%s\n' "同一局域网可断开 USB 使用。"; fi
