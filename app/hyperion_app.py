"""Запуск окна Hyperion на macOS и Windows: python -m app.hyperion_app"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.glass import apply_glass_font
from app.hyperion_window import HyperionWindow


def _bundle() -> Path | None:
    binary = Path(sys.argv[0]).resolve()
    if binary.name == "Hyperion" and binary.parent.name == "MacOS":
        return binary.parents[2]
    neighbor = Path(__file__).resolve().parents[1] / "Hyperion.app"
    return neighbor if neighbor.is_dir() else None


def ensure_login() -> None:
    """Открывать Hyperion при входе в систему."""
    bundle = _bundle()
    if bundle is None:
        return
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / "com.ampilight.hyperion.lan.plist"
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ampilight.hyperion.lan</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>{bundle}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>LimitLoadToSessionType</key>
  <string>Aqua</string>
</dict>
</plist>
"""
    if plist.is_file() and plist.read_text(encoding="utf-8") == body:
        return
    plist.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    apply_glass_font(app)
    app.setApplicationName("Ampilight")
    bundle = _bundle()
    if bundle is not None:
        icon = bundle / "Contents" / "Resources" / "AppIcon.icns"
        if icon.is_file():
            app.setWindowIcon(QIcon(str(icon)))
    ensure_login()
    window = HyperionWindow()
    window.show()
    if "--selftest" in argv:
        def finish() -> None:
            window.grab().save("/tmp/hyperion_ui.png")
            print(
                f"HYPERION_UI ok size={window.width()}x{window.height()} "
                f"host={window.host.text()!r} button={window.connect_button.text()!r} "
                f"send={window.send_button.text()!r} clear={window.clear_button.text()!r}"
            )
            app.exit(0)

        QTimer.singleShot(400, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
