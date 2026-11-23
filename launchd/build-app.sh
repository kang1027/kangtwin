#!/bin/bash
# ~/Applications/Kang Twin.app 을 만든다. 화면에 안 보이는 앱(LSUIElement)이고, 하는 일은 bin/kt-app-entry 실행뿐.
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HOME/Applications/Kang Twin.app"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script quoted form of \"$REPO/bin/kt-app-entry\""
PL="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PL"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier io.kangtwin.app" "$PL" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string io.kangtwin.app" "$PL"
codesign --force --deep -s - "$APP"
echo "만듦: $APP"
