import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app.window import MainWindow, apply_app_theme


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    apply_app_theme(app)
    window = MainWindow()
    window.show()
    if "--camera" in argv:
        QTimer.singleShot(0, window.start_from_camera)
    elif "--desk" in argv:
        QTimer.singleShot(0, window.start_desk_screen)
    elif "--ready" in argv:
        QTimer.singleShot(0, window._show_control)
    if "--selftest" in argv:
        def finish() -> None:
            print(
                f"SELFTEST frames={window.frames_seen} mean={window.last_mean:.1f} "
                f"error={window.grab_error!r}"
            )
            app.exit(0 if window.frames_seen > 0 else 1)

        QTimer.singleShot(2200, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
