THEME = """
* { outline: none; }
#root { background: #101114; }
QLabel { color: #f3f1ea; background: transparent; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#hint { color: #8f918a; font-size: 12px; }
QLabel#section {
    color: #a39a86;
    font-size: 11px;
    font-weight: 600;
}
QLabel#count { color: #f3f1ea; font-size: 13px; font-weight: 600; }
QLabel#field { color: #c8c6be; font-size: 12px; }
#panel {
    background: #17191f;
    border: 1px solid #2a2d34;
    border-radius: 18px;
}
#hairline { background: #2a2d34; border: none; max-height: 1px; }
QScrollArea { background: transparent; border: none; }
QCheckBox { color: #f3f1ea; spacing: 8px; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid #3a3d44;
    background: #101114;
}
QCheckBox::indicator:checked {
    background: #e6b34d;
    border-color: #e6b34d;
}
QSpinBox, QComboBox, QLineEdit {
    background: #101114;
    border: 1px solid #2e3138;
    border-radius: 8px;
    padding: 6px 8px;
    color: #f3f1ea;
    min-height: 20px;
}
QSpinBox:focus, QLineEdit:focus, QComboBox:focus { border-color: #e6b34d; }
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #17191f;
    color: #f3f1ea;
    selection-background-color: #3a3424;
    border: 1px solid #2e3138;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #2c2f36;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #e6b34d;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: #f6f3ea;
    border-radius: 8px;
}
QPushButton {
    background: #101114;
    color: #f3f1ea;
    border: 1px solid #2e3138;
    border-radius: 10px;
    padding: 8px 12px;
}
QPushButton:hover { border-color: #4a4536; }
QPushButton:checked {
    background: #2c281c;
    color: #ffd978;
    border-color: #e6b34d;
}
QPushButton#segment { padding: 6px 4px; font-size: 12px; }
QPushButton#startButton {
    background: #ffd36a;
    color: #1c1608;
    border: none;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 16px;
}
QPushButton#startButton:hover { background: #ffde8a; }
QPushButton#startButton[running="true"] {
    background: #232824;
    color: #d9ffd0;
    border: 1px solid #3f5c48;
}
QPushButton#ghost { background: transparent; }
QPlainTextEdit#log {
    background: #101114;
    border: 1px solid #2e3138;
    border-radius: 8px;
    color: #c8c6be;
    font-family: Menlo, monospace;
    font-size: 11px;
    padding: 6px;
}
QScrollBar:vertical { width: 10px; background: transparent; margin: 4px 0; }
QScrollBar::handle:vertical {
    background: #34373e;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""
