#!/bin/bash
# Usage: launchd/install.sh [--rebuild-app]
# Kang Twin.app을 만들고 수신 데몬 LaunchAgent를 올린다. 정시 작업은 데몬 안의 스케줄러가 띄운다.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="${KANGTWIN_LABEL:-io.kangtwin.receiver}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/kang-twin"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# open -W를 내려도 앱은 계속 돌 수 있으니 직접 끈다. 두 곳에서 받으면 텔레그램이 409를 준다.
osascript -e 'quit app "Kang Twin"' 2>/dev/null || true
pkill -f "kangtwin.daemon" 2>/dev/null || true
# 앱은 처음 한 번만 만든다. 다시 만들면 macOS가 다른 앱으로 보고 볼트 접근 허용을 다시 물을 수 있다.
if [ "$1" = "--rebuild-app" ] || [ ! -d "$HOME/Applications/Kang Twin.app" ]; then
  "$DIR/build-app.sh"
fi
# 저장소 스킬을 ~/.claude/skills에 링크한다. 이미 있으면 건드리지 않는다.
mkdir -p "$HOME/.claude/skills"
for skill in "$DIR/../skills"/*/; do
  name="$(basename "$skill")"
  [ "${name#_}" = "$name" ] || continue
  [ -e "$HOME/.claude/skills/$name" ] || ln -s "$(cd "$skill" && pwd)" "$HOME/.claude/skills/$name"
done
sed -e "s|__LABEL__|$LABEL|g" -e "s|__HOME__|$HOME|g" "$DIR/receiver.plist.template" > "$PLIST"
plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "올림: $LABEL"
