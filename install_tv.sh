#!/bin/bash
# Ставит Ampilight на Android TV по Wi-Fi через adb.
#   ./install_tv.sh            — спросит IP телевизора
#   ./install_tv.sh 192.168.100.20
set -e
cd "$(dirname "$0")"

APK="Ampilight-TV.apk"
ADB="$(command -v adb || echo "$HOME/Library/Android/sdk/platform-tools/adb")"

echo "Собираю свежую версию приложения…"
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
(cd android && ./gradlew assembleDebug -q --console=plain)
cp android/app/build/outputs/apk/debug/app-debug.apk "$APK"
mkdir -p "$HOME/Public/Ampilight" && cp "$APK" "$HOME/Public/Ampilight/"
echo "Свежий APK лежит и в общей папке: Общие → Ampilight."

TV="$1"
if [ -z "$TV" ]; then
  echo "На телевизоре: Настройки → Об устройстве → 7 раз нажми на «Сборка»,"
  echo "затем Настройки → Для разработчиков → включи «Отладка по USB» / «Отладка по сети»."
  echo "IP телевизора: Настройки → Сеть → текущая сеть."
  read -r -p "IP телевизора: " TV
fi
[ -z "$TV" ] && { echo "IP не указан."; exit 1; }
case "$TV" in *:*) ;; *) TV="$TV:5555" ;; esac

wait_device() {
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    state="$("$ADB" -s "$TV" get-state 2>/dev/null || true)"
    [ "$state" = "device" ] && return 0
    sleep 2
  done
  return 1
}

echo "Подключаюсь к $TV. На телевизоре может появиться вопрос «Разрешить отладку?» — нажми «Разрешить»."
"$ADB" connect "$TV" || true
if ! wait_device; then
  # Android TV 11+: «Беспроводная отладка» сначала требует сопряжения по коду.
  echo
  echo "Не подключилось. На Android 11+ нужно сопряжение (один раз):"
  echo "Для разработчиков → Беспроводная отладка → «Подключить устройство с помощью кода»."
  echo "На экране будут IP:порт и шестизначный код."
  read -r -p "IP:порт сопряжения (Enter — пропустить): " PAIR
  if [ -n "$PAIR" ]; then
    read -r -p "Код: " CODE
    "$ADB" pair "$PAIR" "$CODE"
    echo "Теперь адрес для подключения — на экране «Беспроводная отладка» (IP:порт, не тот, что для кода)."
    read -r -p "IP:порт подключения: " TV
    "$ADB" connect "$TV" || true
  fi
  if ! wait_device; then
    echo "Телевизор не дал подключиться. Проверь, что отладка включена, и запусти ещё раз."
    exit 1
  fi
fi

echo "Ставлю приложение…"
"$ADB" -s "$TV" install -r "$APK"
"$ADB" -s "$TV" shell am start -n com.ampilight.tv/.MainActivity
echo "Готово. Ampilight открыт на телевизоре."
