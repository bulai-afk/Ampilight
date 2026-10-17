#!/bin/bash
# Собирает Hyperion.dmg: двойной щелчок ставит приложение в «Программы».
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/.pyenv/versions/3.11.9/bin/python3}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

mkdir -p build dist/dmg
clang -fobjc-arc -O2 \
  native/sck_helper.m native/sck_capture.m \
  -framework AppKit -framework Foundation -framework ScreenCaptureKit \
  -framework CoreMedia -framework CoreVideo \
  -o build/sck-helper

"$PY" -m pip install --disable-pip-version-check pyinstaller
"$PY" -m PyInstaller macos/hyperion.spec --noconfirm --distpath dist --workpath build/pyinstaller

APP="dist/Hyperion.app"
BIN="$APP/Contents/MacOS"
mv "$BIN/Hyperion" "$BIN/Hyperion.bin"
cp build/sck-helper "$BIN/sck-helper"
chmod +x "$BIN/sck-helper" "$BIN/Hyperion.bin"

cat > "$BIN/Hyperion" <<'EOF'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$DIR/../.." && pwd)"
DEST="/Applications/Hyperion.app"
if [[ "$APP" != "$DEST" ]]; then
  lang="$(defaults read -g AppleLanguages 2>/dev/null | awk 'NR==2 { gsub(/[",]/, ""); print; exit }')"
  case "$lang" in
    en*)
      osascript -e 'display dialog "Hyperion will be installed in Applications and then opened." buttons {"Install"} default button "Install" with title "Hyperion"'
      ;;
    *)
      osascript -e 'display dialog "Hyperion установится в папку «Программы» и откроется." buttons {"Установить"} default button "Установить" with title "Hyperion"'
      ;;
  esac
  rm -rf "$DEST"
  cp -R "$APP" "$DEST"
  xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
  chmod +x "$DEST/Contents/MacOS/Hyperion" "$DEST/Contents/MacOS/Hyperion.bin" "$DEST/Contents/MacOS/sck-helper"
  open "$DEST"
  exit 0
fi
exec "$DIR/Hyperion.bin" "$@"
EOF
chmod +x "$BIN/Hyperion"

mkdir -p "$APP/Contents/Resources/en.lproj" "$APP/Contents/Resources/ru.lproj"
cat > "$APP/Contents/Resources/en.lproj/InfoPlist.strings" <<'EOF'
"NSScreenCaptureUsageDescription" = "Hyperion sends the screen image to the lights.";
"NSLocalNetworkUsageDescription" = "Hyperion looks for the light server on the local network.";
EOF
cat > "$APP/Contents/Resources/ru.lproj/InfoPlist.strings" <<'EOF'
"NSScreenCaptureUsageDescription" = "Hyperion передаёт изображение экрана на подсветку.";
"NSLocalNetworkUsageDescription" = "Hyperion ищет сервер подсветки в локальной сети.";
EOF

codesign --force --deep --sign - "$APP"

rm -rf dist/dmg
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/Hyperion.app
ln -s /Applications dist/dmg/Applications
hdiutil create -volname Hyperion -srcfolder dist/dmg -ov -format UDZO dist/Hyperion.dmg
echo "готово: dist/Hyperion.dmg"
