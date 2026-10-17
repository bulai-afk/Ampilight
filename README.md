# Ampilight

**Русский** · [English](#english)

Это **неофициальное** приложение. Его нет в составе [Hyperion.ng](https://github.com/hyperion-project/hyperion.ng) и Home Assistant. Это личная разработка: программа написана под свою подсветку и свои привычки, а не как общий продукт. Интерфейс только на русском.

Скачать установщик: **[Hyperion.dmg](https://github.com/bulai-afk/Ampilight/releases/latest/download/Hyperion.dmg)**  
Все файлы выпуска: [страница Releases](https://github.com/bulai-afk/Ampilight/releases/latest)

<p>
  <img src="docs/screenshots/search.png" width="220" alt="Поиск сервера Hyperion">
  <img src="docs/screenshots/connect.png" width="220" alt="Адрес, порт и пароль">
  <img src="docs/screenshots/control.png" width="220" alt="Стол в режиме Адаптив">
  <img src="docs/screenshots/settings.png" width="220" alt="Диоды и область захвата">
</p>

Программа на Mac отдаёт картинку экрана серверу Hyperion, и светодиодная лента повторяет её. Телефон через Home Assistant и это окно делят один сервер: на ленте остаётся тот, кто задал цвет последним.

Комментарии можно оставлять: чего не хватает и что интересно было бы развивать. Если приложением реально будут пользоваться, это можно доделать. Пишите в [Issues](https://github.com/bulai-afk/Ampilight/issues).

## Установка

1. Скачайте [Hyperion.dmg](https://github.com/bulai-afk/Ampilight/releases/latest/download/Hyperion.dmg).
2. Дважды нажмите скачанный файл.
3. Дважды нажмите **Hyperion**. Приложение само копируется в «Программы» и открывается. Python ставить не нужно.

Если macOS скажет, что разработчик не проверен, нажмите Hyperion правой кнопкой и выберите «Открыть». Это один раз: у сборки своя подпись, без аккаунта Apple.

Дальше разрешите запись экрана и локальную сеть, выберите сервер и режим **Адаптив**. Захват экрана запускается вместе с приложением.

Исходники и запуск без установщика описаны ниже.

## Что нужно

- Hyperion.ng в одной сети с компьютером. Подойдёт Raspberry Pi или дополнение Home Assistant.
- macOS 12 или новее. Захват экрана сделан через ScreenCaptureKit и работает только на Mac.
- Для запуска из исходников — Python 3.11 и пакеты из `requirements.txt`. В установщике Python уже внутри.
- Лента, которую Hyperion уже умеет зажигать: ESP32 по DDP или Arduino по Adalight. Приложение не заменяет прошивку платы, оно отдаёт Hyperion картинку.

Порт JSON API Hyperion — **19444**. Веб-интерфейс обычно на порту **8090**. Пароль по умолчанию у Hyperion — `hyperion`. Если вы его меняли, в программе нужен новый.

## 1. Hyperion

1. Откройте веб-интерфейс Hyperion и убедитесь, что экземпляр ленты включён, а устройство (LED device) запущено.
2. В настройках сети должен быть включён JSON-сервер, порт `19444`. Без него программа не подключится.
3. Запомните адрес сервера в локальной сети, например `192.168.1.20`.
4. Для стола с ESP32 устройство — `udpddp`, порт `4048`. Порядок цвета (`colorOrder`) оставьте тем, при котором заливка из самого Hyperion выглядит правильно. Для телевизора с Nano обычно Adalight на последовательном порту.
5. Раскладка диодов должна совпадать с проводом. У стола в этом проекте первый диод — правый край, цепочка идёт влево. Каждый диод — вертикальный срез кадра на всю высоту: Hyperion берёт цвет из прямоугольника, а программа заранее кладёт в него уже посчитанный цвет.

Эффект с именем **Адаптив** создавать вручную не нужно. Программа добавляет его на сервер при подключении. Это чёрная заглушка. Живая картинка приходит отдельным кадром и перекрывает заглушку.

## 2. Запуск из исходников

В каталоге проекта:

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m app.hyperion_app
```

`Hyperion.app` в корне репозитория и `Hyperion.command` — это запуск для разработки. Они ищут Python в `~/.pyenv/versions/3.11.9`. Установщик из Releases от Python на компьютере не зависит.

При первом запуске macOS спросит два разрешения. Оба нужны:

- **Запись экрана** — иначе захвата не будет.
- **Локальная сеть** — иначе программа не увидит Hyperion.

Разрешения лежат в «Системные настройки → Конфиденциальность и безопасность». После включения запись экрана программу надо запустить ещё раз.

Окно само прячется в строку меню. Иконка телевизора открывает превью захвата, кнопки «Запустить» / «Остановить», «Открыть» и «Выйти». Закрытие окна программу не завершает.

## 3. Подключение к серверу

<img src="docs/screenshots/search.png" width="240" alt="Найденный сервер Hyperion">
<img src="docs/screenshots/connect.png" width="240" alt="Ручной ввод адреса и пароля">

1. На первом экране программа ищет Hyperion в сети. Выберите свой сервер. Если список пустой, откройте ввод адреса вручную.
2. Адрес — IP Hyperion. Порт — `19444`. Пароль — пароль JSON API.
3. Нажмите **Подключить**.

Адрес запоминается, в следующий раз программа подключается сама. Захват из установщика читает этот же адрес.

Дальше выберите прибор. Имя экземпляра в Hyperion должно быть **Стол** или **Телевизор** — по нему программа понимает, куда слать картинку.

## 4. Захват экрана ноутбука

В установленной программе захват стартует сам. При запуске из исходников его поднимает отдельный процесс. Пока он не запущен, режим «Адаптив» только включает чёрную заглушку.

Запуск вручную:

```bash
python3.11 -u -m app.desk_screen
```

Адрес сервера процесс берёт из настроек окна. Если окно ещё ни разу не подключалось, в начале `app/desk_screen.py` можно задать свои значения: `HOST`, `PORT`, `PASSWORD`, `DESK`. Плату процесс ищет сам по UDP `4210`.

В выводе должно появиться `жду режим «Адаптив»`, затем `захват …%` и строки `кадр`. Окно терминала не закрывайте: вместе с ним остановится захват.

В программе выберите **Стол** и режим **Адаптив**. Лента начнёт повторять нижнюю полосу экрана.

<img src="docs/screenshots/control.png" width="240" alt="Прибор Стол, режим Адаптив">

Как это устроено в Hyperion:

- Кадр экрана идёт с приоритетом **100**. Меньшее число сильнее.
- Цвет и эффекты из этой программы и из Home Assistant идут с приоритетом **128**.
- Пока выбран «Адаптив», картинка экрана перекрывает заливку.
- Цвет, другой эффект или выключение снимают кадр. Лента не должна оставаться на последней картинке.
- Закрытая крышка гасит диоды. После открытия захват поднимается снова. Пока Mac спит, плата ещё может держать последний кадр: погасить его можно только когда компьютер проснулся.

Тёмный участок кадра гасит свой диод. Красный не подмешивается к белым бликам меню, иначе лента уходит в розовый.

### Область захвата

<img src="docs/screenshots/settings.png" width="240" alt="Число диодов, область захвата и диапазон ленты">

В настройках программы два ползунка.

**Область захвата** — вертикальная полоса экрана в процентах высоты. Для нижнего меню macOS оставьте последние несколько процентов, примерно `93–100`. Полоса выше меню на меню не реагирует.

**Диапазон ленты** — какой кусок ширины экрана растягивается на диоды. `0–100` — весь экран. Число диодов снизу должно совпадать с лентой. Подпись в окне: «Диод 1 — правый край стола, дальше цепочка идёт влево».

Ползунки читаются процессом захвата сразу, перезапускать его из‑за них не нужно.

## 5. Телевизор

На экземпляре **Телевизор** режим **Адаптив** включает граббер, который уже настроен в Hyperion (обычно USB-карта захвата, V4L). Картинку телевизора снимает сервер, не этот Mac.

Цвет и любой другой эффект граббер выключают, чтобы заливка с телефона и с компьютера была видна. Снова включить картинку телевизора — снова выбрать «Адаптив».

## 6. Если лента не повторяет экран

- В строке меню захват выключен — нажмите «Запустить» и проверьте, что процесс захвата жив.
- `Hyperion не пустил` — неверный пароль или JSON-сервер выключен.
- Список серверов пуст — Mac и Hyperion в разных сетях, либо нет разрешения на локальную сеть.
- Кадры в терминале есть, лента молчит — в Hyperion выключено устройство ленты или неверный IP платы. Процесс пишет `стол: плата …`, когда находит ESP.
- Лента белая — Hyperion смотрит не в те прямоугольники. Раскладка диодов должна быть вертикальными срезами на всю высоту кадра.
- Цвет не тот — не меняйте `colorOrder`, пока заливка одним цветом из веб-интерфейса Hyperion не станет верной. Захват пользуется тем же порядком.
- После сна картинка застыла — захват должен погасить ленту и начаться заново.

## Прошивка платы

`firmware/esp32_wifi` — прошивка ESP32: Wi‑Fi, DDP на порту `4048` и ответ на поиск. Пароль сети в репозиторий не входит. В `config.h` лежат заглушки `wifi-name` и `wifi-password`. Свой пароль вводится при прошивке (`Прошить ESP32.command` или `python3 flash_esp32.py`) и остаётся только на плате.

`firmware/arduino_nano` — прошивка Adalight для телевизора. Уже прошитую плату перепрошивать не нужно.

---

## English

This is an **unofficial** app. It is not part of [Hyperion.ng](https://github.com/hyperion-project/hyperion.ng) or Home Assistant. It is a personal project, written for the author's own lights and habits, not as a general product. The app itself is Russian only: buttons, menus, and messages are not translated.

Download the installer: **[Hyperion.dmg](https://github.com/bulai-afk/Ampilight/releases/latest/download/Hyperion.dmg)**  
All release files: [Releases](https://github.com/bulai-afk/Ampilight/releases/latest)

<p>
  <img src="docs/screenshots/search.png" width="220" alt="Hyperion server search">
  <img src="docs/screenshots/connect.png" width="220" alt="Address, port, and password">
  <img src="docs/screenshots/control.png" width="220" alt="Desk in Adaptive mode">
  <img src="docs/screenshots/settings.png" width="220" alt="LED counts and capture area">
</p>

The Mac app sends the screen to a Hyperion server, and the LED strip follows that picture. A phone using Home Assistant and this window share one server: the last one to set a color is what the strip shows.

Comments are welcome: what is missing, and what would be worth developing. If people actually use the app, those parts can be finished. Write in [Issues](https://github.com/bulai-afk/Ampilight/issues).

### Install

1. Download [Hyperion.dmg](https://github.com/bulai-afk/Ampilight/releases/latest/download/Hyperion.dmg).
2. Double-click the downloaded file.
3. Double-click **Hyperion**. The app copies itself into Applications and opens. You do not install Python.

If macOS says the developer cannot be verified, right-click Hyperion and choose Open. That prompt appears once: the build is signed locally, without an Apple developer account.

Then allow screen recording and local network access, pick your server, and choose the mode **Адаптив** (Adaptive). Screen capture starts with the app. The label in the window stays in Russian.

Running from source, without the installer, is described below.

### What you need

- Hyperion.ng on the same network as the computer. A Raspberry Pi or the Home Assistant add-on both work.
- macOS 12 or newer. Screen capture uses ScreenCaptureKit and only works on a Mac.
- Python 3.11 and the packages in `requirements.txt`, only if you run from source. The installer already contains Python.
- A strip Hyperion can already drive: an ESP32 over DDP, or an Arduino over Adalight. This app does not replace the board firmware. It sends a picture to Hyperion.

Hyperion's JSON API port is **19444**. The web interface is usually on port **8090**. Hyperion's default password is `hyperion`. If you changed it, the app needs the new one.

### 1. Hyperion

1. Open the Hyperion web interface and check that the strip instance is on and the LED device is running.
2. The JSON server must be enabled on port `19444`. Without it the app cannot connect.
3. Note the server address on your LAN, for example `192.168.1.20`.
4. For a desk ESP32 the device type is `udpddp`, port `4048`. Leave `colorOrder` as whatever makes a solid color from Hyperion itself look right. A TV on a Nano is usually Adalight on a serial port.
5. The LED layout has to match the wiring. In this project the first desk LED is the right edge and the chain runs left. Each LED is a full-height vertical slice of the frame: Hyperion samples a rectangle, and the app fills that rectangle with the color it already computed.

You do not create an effect named **Адаптив** by hand. The app adds it when it connects. That effect is a black placeholder. The live picture arrives as a separate frame and covers the placeholder.

### 2. Run from source

From the project directory:

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m app.hyperion_app
```

`Hyperion.app` in the repository root and `Hyperion.command` are the development launchers. They look for Python in `~/.pyenv/versions/3.11.9`. The Releases installer does not need Python on the machine.

On the first launch macOS asks for two permissions. Both are required:

- **Screen Recording**, or there is no capture.
- **Local Network**, or the app cannot see Hyperion.

They live in System Settings → Privacy & Security. After you allow screen recording, start the app again.

The window hides to the menu bar. The TV icon opens the capture preview and the buttons «Запустить» / «Остановить» (Start / Stop), «Открыть» (Open), and «Выйти» (Quit). Closing the window does not quit the app.

### 3. Connect to the server

<img src="docs/screenshots/search.png" width="240" alt="A Hyperion server found on the network">
<img src="docs/screenshots/connect.png" width="240" alt="Manual address and password">

1. The first screen searches the network for Hyperion. Pick your server. If the list is empty, open manual entry. The button says «Подключиться вручную».
2. The address is the Hyperion IP. The port is `19444`. The password is the JSON API password.
3. Press **Подключить** (Connect).

The address is remembered, and the next launch connects by itself. Capture from the installer reads that same address.

Then pick the device. The Hyperion instance name should be **Стол** (desk) or **Телевизор** (TV). The app uses that name to decide where the picture goes.

### 4. Laptop screen capture

The installed app starts capture on its own. From source, a separate process does it. Until that process is running, **Адаптив** only turns on the black placeholder.

Start it by hand:

```bash
python3.11 -u -m app.desk_screen
```

The process takes the server address from the app's saved settings. If the window has never connected, set `HOST`, `PORT`, `PASSWORD`, and `DESK` at the top of `app/desk_screen.py`. The board is found on its own over UDP `4210`.

The log should show `жду режим «Адаптив»`, then `захват …%`, then `кадр` lines. Leave the terminal open: closing it stops capture.

In the app, choose **Стол** and the mode **Адаптив**. The strip follows the bottom band of the screen.

<img src="docs/screenshots/control.png" width="240" alt="Desk selected, Adaptive mode">

How this sits inside Hyperion:

- Screen frames use priority **100**. A lower number wins.
- Colors and effects from this app and from Home Assistant use priority **128**.
- While **Адаптив** is selected, the screen covers a solid color.
- A color, another effect, or switching off removes the frame. The strip should not keep the last picture.
- Closing the laptop turns the LEDs off. Opening it starts capture again. While the Mac is asleep the board can still hold the last frame: it can only be cleared once the computer wakes.

A dark part of the frame turns its LED off. Red is not mixed with white menu highlights, which would make the strip look pink.

#### Capture area

<img src="docs/screenshots/settings.png" width="240" alt="LED counts, capture band, and strip range">

The settings screen has two sliders.

**Область захвата** (capture area) is a vertical band, in percent of screen height. For the macOS Dock, keep the last few percent, about `93–100`. A band above the Dock does not react to the Dock.

**Диапазон ленты** (strip range) is how much of the screen width is spread across the LEDs. `0–100` is the whole screen. The bottom LED count should match the strip. The note in the window says the first LED is the right edge of the desk and the chain runs left.

The capture process reads the sliders live. You do not restart it when you move them.

### 5. Television

On the **Телевизор** instance, **Адаптив** enables the grabber already configured in Hyperion, usually a USB capture card (V4L). The server grabs the TV picture, not this Mac.

A color or any other effect turns that grabber off, so a fill from the phone or the computer can show. To bring the TV picture back, choose **Адаптив** again.

### 6. If the strip does not follow the screen

- Capture is off in the menu bar. Press «Запустить» and check that the capture process is still running.
- `Hyperion не пустил` means a wrong password or the JSON server is disabled.
- The server list is empty: the Mac and Hyperion are on different networks, or local network permission is missing.
- The log shows frames but the strip stays dark: the LED device is off in Hyperion, or the board IP is wrong. The process prints `стол: плата …` when it finds the ESP.
- The strip is white: Hyperion is sampling the wrong rectangles. LEDs should be full-height vertical slices.
- The hue is wrong: do not change `colorOrder` until a solid color from the Hyperion web interface looks right. Capture uses that same order.
- After sleep the picture is frozen: capture should turn the strip off and start again.

### Board firmware

`firmware/esp32_wifi` is the ESP32 firmware: Wi‑Fi, DDP on port `4048`, and a discovery reply. The Wi‑Fi password is not in the repository. `config.h` contains the placeholders `wifi-name` and `wifi-password`. Your password is entered when flashing (`Прошить ESP32.command` or `python3 flash_esp32.py`) and stays on the board.

`firmware/arduino_nano` is the Adalight firmware for a TV. A board that is already flashed does not need to be flashed again.
