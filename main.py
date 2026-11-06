import sys
import os
import math
import time
import json
import re
import threading
import ctypes
from PIL import Image, ImageDraw, ImageFont

from PySide6.QtCore import Qt, QSize, QPoint, QRect, Signal, QObject
from PySide6.QtGui import (
    QIcon, QPixmap, QImage, QColor, QFont, QKeySequence, QShortcut,
    QGuiApplication, QPainter, QPen
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QLineEdit, QFileDialog, QDialog,
    QFormLayout, QSpinBox, QColorDialog, QMessageBox, QFrame, QSplitter,
    QStatusBar, QGridLayout, QGroupBox, QCheckBox
)

from config import AppConfig
from icons import get_qicon, get_qpixmap
from canvas_editor import CanvasEditor, pil_to_qpixmap
from capture import CaptureOverlay
from collage_editor import CollageEditorDialog


def get_dark_qss():
    return """
    QMainWindow, QDialog {
        background-color: #121417;
        color: #E5E7EB;
    }
    QFrame#toolbar_frame {
        background-color: #1A1D23;
        border-radius: 8px;
    }
    QFrame#toolbar_border_frame {
        background-color: #2A2E35;
        border-radius: 10px;
    }
    QPushButton {
        background-color: transparent;
        color: #E5E7EB;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px;
    }
    QPushButton:hover {
        background-color: #2D323C;
        border: 1px solid #404654;
    }
    QPushButton:pressed {
        background-color: #005FB8;
    }
    QPushButton:checked {
        background-color: #005FB8;
        border: 1px solid #00E5FF;
    }
    QPushButton:checked:hover {
        background-color: #007AFF;
        border: 1px solid #00E5FF;
    }
    QPushButton#btn_new {
        background-color: #005FB8;
        color: #FFFFFF;
        font-weight: bold;
        padding: 4px 10px;
        border-radius: 4px;
    }
    QPushButton#btn_new:hover {
        background-color: #007AFF;
    }
    QComboBox {
        background-color: #1E2228;
        color: #E5E7EB;
        border: 1px solid #333842;
        border-radius: 4px;
        padding: 2px 6px;
    }
    QComboBox:hover {
        border: 1px solid #005FB8;
    }
    QComboBox::drop-down {
        border: none;
    }
    QLineEdit {
        background-color: #1E2228;
        color: #E5E7EB;
        border: 1px solid #333842;
        border-radius: 4px;
        padding: 2px 6px;
    }
    QStatusBar {
        background-color: #121417;
        color: #888888;
        font-family: Consolas, monospace;
        font-size: 11px;
    }
    """

def get_light_qss():
    return """
    QMainWindow, QDialog {
        background-color: #F3F4F6;
        color: #1F2937;
    }
    QFrame#toolbar_frame {
        background-color: #FFFFFF;
        border-radius: 8px;
    }
    QFrame#toolbar_border_frame {
        background-color: #E5E7EB;
        border-radius: 10px;
    }
    QPushButton {
        background-color: transparent;
        color: #374151;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 4px;
    }
    QPushButton:hover {
        background-color: #F3F4F6;
        border: 1px solid #D1D5DB;
    }
    QPushButton:pressed {
        background-color: #005FB8;
        color: #FFFFFF;
    }
    QPushButton:checked {
        background-color: #005FB8;
        color: #FFFFFF;
        border: 1px solid #00E5FF;
    }
    QPushButton:checked:hover {
        background-color: #007AFF;
        color: #FFFFFF;
        border: 1px solid #00E5FF;
    }
    QPushButton#btn_new {
        background-color: #005FB8;
        color: #FFFFFF;
        font-weight: bold;
        padding: 4px 10px;
        border-radius: 4px;
    }
    QPushButton#btn_new:hover {
        background-color: #007AFF;
    }
    QComboBox {
        background-color: #FFFFFF;
        color: #1F2937;
        border: 1px solid #D1D5DB;
        border-radius: 4px;
        padding: 2px 6px;
    }
    QComboBox:hover {
        border: 1px solid #005FB8;
    }
    QLineEdit {
        background-color: #FFFFFF;
        color: #1F2937;
        border: 1px solid #D1D5DB;
        border-radius: 4px;
        padding: 2px 6px;
    }
    QStatusBar {
        background-color: #F3F4F6;
        color: #6B7280;
        font-family: Consolas, monospace;
        font-size: 11px;
    }
    """


class SnippingToolApp(QMainWindow):
    hotkey_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Snipping Tool")

        self.config = AppConfig()
        self.overlay = None
        self.tool_buttons = {}
        self.icon_size_px = 18
        self.btn_size_px = 30
        self.brand_size_px = 22

        logo_path = os.path.join(os.path.dirname(__file__), "SnippingTool.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

        self.setup_ui()
        self.apply_theme()
        self.load_settings()
        self.setup_shortcuts()

        # Connect global hotkey signal
        self.hotkey_signal.connect(self.start_capture)
        self.start_global_hotkey_listener()

        # Fit initial launcher size (minimal compact widget mode)
        self.resize(560, 220)
        self.center_window()
        self.show_launcher_mode()

    def start_global_hotkey_listener(self):
        """Starts a background thread to listen for the global Shift + Print Screen hotkey (Windows only)."""
        if os.name != 'nt':
            return

        def listener():
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            MOD_SHIFT = 0x0004
            VK_SNAPSHOT = 0x2C  # Print Screen
            WM_HOTKEY = 0x0312
            HOTKEY_ID = 101

            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_SHIFT, VK_SNAPSHOT):
                return

            try:
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        self.hotkey_signal.emit()
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                user32.UnregisterHotKey(None, HOTKEY_ID)

        self.hotkey_thread = threading.Thread(target=listener, daemon=True)
        self.hotkey_thread.start()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Floating Toolbar Container
        self.toolbar_border_frame = QFrame()
        self.toolbar_border_frame.setObjectName("toolbar_border_frame")
        toolbar_border_layout = QVBoxLayout(self.toolbar_border_frame)
        toolbar_border_layout.setContentsMargins(1, 1, 1, 1)

        self.toolbar_frame = QFrame()
        self.toolbar_frame.setObjectName("toolbar_frame")
        toolbar_layout = QHBoxLayout(self.toolbar_frame)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(6)

        # --- LEFT GROUP: Brand + Capture Controls ---
        left_grp = QHBoxLayout()
        left_grp.setSpacing(6)

        # Brand Logo + Title
        logo_path = os.path.join(os.path.dirname(__file__), "SnippingTool.png")
        if os.path.exists(logo_path):
            lbl_brand_icon = QLabel()
            pixmap = QPixmap(logo_path).scaled(self.brand_size_px, self.brand_size_px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            lbl_brand_icon.setPixmap(pixmap)
            left_grp.addWidget(lbl_brand_icon)

        lbl_title = QLabel("Snipping Tool")
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        left_grp.addWidget(lbl_title)

        # New Snip Button
        self.btn_new = QPushButton(" New")
        self.btn_new.setObjectName("btn_new")
        self.btn_new.setIcon(get_qicon("camera", "#FFFFFF", (20, 20)))
        self.btn_new.setIconSize(QSize(20, 20))
        self.btn_new.clicked.connect(self.start_capture)
        left_grp.addWidget(self.btn_new)

        # Capture Mode Combobox
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["free", "fixed"])
        self.cb_mode.setCurrentText(self.config.get("default_capture_mode"))
        self.cb_mode.currentTextChanged.connect(self.on_mode_changed)
        left_grp.addWidget(self.cb_mode)

        # Fixed W/H inputs
        left_grp.addWidget(QLabel("W:"))
        self.entry_w = QLineEdit(str(self.config.get("fixed_width")))
        self.entry_w.setFixedWidth(45)
        left_grp.addWidget(self.entry_w)

        left_grp.addWidget(QLabel("H:"))
        self.entry_h = QLineEdit(str(self.config.get("fixed_height")))
        self.entry_h.setFixedWidth(45)
        left_grp.addWidget(self.entry_h)

        toolbar_layout.addLayout(left_grp)

        # Divider
        toolbar_layout.addWidget(self.make_v_divider())

        # --- MIDDLE GROUP: Vector Tools (Hidden initially in Minimal Mode) ---
        self.mid_tools_container = QWidget()
        mid_grp = QHBoxLayout(self.mid_tools_container)
        mid_grp.setContentsMargins(0, 0, 0, 0)
        mid_grp.setSpacing(3)

        tools = [
            ("select", "pointer", "Select & Move Text"),
            ("pencil", "pencil", "Pencil Brush"),
            ("highlighter", "highlighter", "Translucent Highlighter"),
            ("eraser", "eraser", "Object Eraser"),
            ("text", "text", "Add Text Annotations"),
            ("crop", "crop", "Crop Snippet Area"),
            ("line", "line", "Straight Line"),
            ("arrow", "arrow", "Vector Arrow"),
            ("rectangle", "rectangle", "Rectangle outline"),
            ("circle", "circle", "Circle/Ellipse")
        ]

        self.tool_icon_names = {}
        icon_color = "#E5E7EB" if self.config.get("theme") == "dark" else "#333333"

        for tool_name, icon_name, tooltip in tools:
            self.tool_icon_names[tool_name] = icon_name
            btn = QPushButton()
            btn.setIcon(get_qicon(icon_name, icon_color, (self.icon_size_px, self.icon_size_px)))
            btn.setIconSize(QSize(self.icon_size_px, self.icon_size_px))
            btn.setFixedSize(self.btn_size_px, self.btn_size_px)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, t=tool_name: self.set_tool(t))
            mid_grp.addWidget(btn)
            self.tool_buttons[tool_name] = btn

        mid_grp.addWidget(self.make_v_divider())

        # Stroke thickness
        self.cb_thickness = QComboBox()
        self.cb_thickness.addItems(["1", "2", "3", "5", "8", "12", "16", "24"])
        self.cb_thickness.setCurrentText(str(self.config.get("last_thickness")))
        self.cb_thickness.currentTextChanged.connect(self.on_style_changed)
        mid_grp.addWidget(self.cb_thickness)

        # Fill mode
        self.cb_fill = QComboBox()
        self.cb_fill.addItems(["hollow", "filled"])
        self.cb_fill.setCurrentText(self.config.get("last_fill_mode"))
        self.cb_fill.currentTextChanged.connect(self.on_style_changed)
        mid_grp.addWidget(self.cb_fill)

        # Font Family
        self.cb_font_family = QComboBox()
        self.cb_font_family.addItems(["Arial", "Times New Roman", "Courier New", "Georgia", "Segoe UI", "Verdana", "Impact"])
        self.cb_font_family.setCurrentText(self.config.get("last_font_family") or "Arial")
        self.cb_font_family.currentTextChanged.connect(self.on_style_changed)
        mid_grp.addWidget(self.cb_font_family)

        # Font size dec/inc
        self.btn_font_dec = QPushButton("A-")
        self.btn_font_dec.setFixedWidth(30)
        self.btn_font_dec.clicked.connect(self.font_dec)
        mid_grp.addWidget(self.btn_font_dec)

        self.cb_font_size = QComboBox()
        self.cb_font_size.addItems(["8", "10", "12", "14", "16", "20", "24", "32", "40", "48", "72"])
        self.cb_font_size.setCurrentText(str(self.config.get("last_font_size")))
        self.cb_font_size.currentTextChanged.connect(self.on_style_changed)
        mid_grp.addWidget(self.cb_font_size)

        self.btn_font_inc = QPushButton("A+")
        self.btn_font_inc.setFixedWidth(30)
        self.btn_font_inc.clicked.connect(self.font_inc)
        mid_grp.addWidget(self.btn_font_inc)

        # Color Swatches
        swatches = ["#FF3B30", "#FFCC00", "#34C759", "#007AFF", "#00E5FF", "#0E1013"]
        for col in swatches:
            s_btn = QPushButton()
            s_btn.setFixedSize(20, 20)
            s_btn.setStyleSheet(f"background-color: {col}; border: 1px solid #777777; border-radius: 10px;")
            s_btn.clicked.connect(lambda _, c=col: self.set_color(c))
            mid_grp.addWidget(s_btn)

        btn_picker = QPushButton("+")
        btn_picker.setFixedSize(22, 22)
        btn_picker.clicked.connect(self.choose_custom_color)
        mid_grp.addWidget(btn_picker)

        toolbar_layout.addWidget(self.mid_tools_container)
        self.mid_tools_container.setVisible(False)
        toolbar_layout.addStretch()

        # --- RIGHT GROUP: Actions ---
        right_grp = QHBoxLayout()
        right_grp.setSpacing(3)

        self.btn_undo = self.make_action_button("undo", self.undo, "Undo (Ctrl+Z)", icon_color)
        right_grp.addWidget(self.btn_undo)

        self.btn_redo = self.make_action_button("redo", self.redo, "Redo (Ctrl+Y)", icon_color)
        right_grp.addWidget(self.btn_redo)

        self.btn_zoom_out = self.make_action_button("zoom_out", self.zoom_out, "Zoom Out (Ctrl+Scroll)", icon_color)
        right_grp.addWidget(self.btn_zoom_out)

        self.btn_zoom_in = self.make_action_button("zoom_in", self.zoom_in, "Zoom In (Ctrl+Scroll)", icon_color)
        right_grp.addWidget(self.btn_zoom_in)

        right_grp.addWidget(self.make_v_divider())

        self.btn_clear = self.make_action_button("clear", self.delete_snippet, "Delete Captured Snippet / Clear Workspace", icon_color)
        right_grp.addWidget(self.btn_clear)

        self.btn_open_file = self.make_action_button("folder_open", self.open_file, "Open Image File (Ctrl+O)", icon_color)
        right_grp.addWidget(self.btn_open_file)

        self.btn_copy = self.make_action_button("copy", self.copy_to_clipboard, "Copy to Clipboard (Ctrl+C)", icon_color)
        right_grp.addWidget(self.btn_copy)

        self.btn_collage = self.make_action_button("collage", self.open_collage_editor, "Photo Collage Editor", icon_color)
        right_grp.addWidget(self.btn_collage)

        self.btn_save_as = self.make_action_button("save", self.save_as, "Save As (Ctrl+Shift+S)", icon_color)
        right_grp.addWidget(self.btn_save_as)

        self.btn_settings = self.make_action_button("settings", self.open_settings_dialog, "Preferences Configuration", icon_color)
        right_grp.addWidget(self.btn_settings)

        toolbar_layout.addLayout(right_grp)

        toolbar_border_layout.addWidget(self.toolbar_frame)
        main_layout.addWidget(self.toolbar_border_frame)

        # Minimal Launcher Card (Cheatsheet & Quick Launch Actions)
        self.setup_launcher_card(main_layout)

        # Center Canvas Workspace Editor
        self.canvas_editor = CanvasEditor()
        main_layout.addWidget(self.canvas_editor, 1)

        self.canvas_editor.cursor_callback = self.update_coords_status
        self.canvas_editor.on_crop_complete_callback = self.on_crop_complete
        self.canvas_editor.on_tool_change_callback = self.set_tool

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.lbl_status_tool = QLabel("TOOL: PENCIL")
        self.lbl_status_zoom = QLabel("ZOOM: 100%")
        self.lbl_status_dims = QLabel("RESOLUTION: 0 x 0 PX")
        self.lbl_status_coords = QLabel("COORDS: 0, 0")
        self.lbl_status_path = QLabel(f"SAVE DEST: {self.config.get('default_save_path')}")

        self.status_bar.addWidget(self.lbl_status_tool)
        self.status_bar.addWidget(self.lbl_status_zoom)
        self.status_bar.addWidget(self.lbl_status_dims)
        self.status_bar.addWidget(self.lbl_status_coords)
        self.status_bar.addPermanentWidget(self.lbl_status_path)

    def setup_launcher_card(self, parent_layout):
        self.launcher_card = QFrame()
        self.launcher_card.setStyleSheet("background-color: #121417; border: 1px solid #2A2E35; border-radius: 8px;")
        card_layout = QVBoxLayout(self.launcher_card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(8)

        # Header with Open File button
        header_lay = QHBoxLayout()
        lbl_welcome = QLabel("⌨️ Keyboard Shortcuts & Quick Actions")
        lbl_welcome.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_welcome.setStyleSheet("color: #00E5FF;")
        header_lay.addWidget(lbl_welcome)
        header_lay.addStretch()

        btn_open = QPushButton(" Open File (Ctrl+O)")
        btn_open.setIcon(get_qicon("folder_open", "#FFFFFF", (16, 16)))
        btn_open.setIconSize(QSize(16, 16))
        btn_open.setStyleSheet("background-color: #005FB8; color: #FFFFFF; font-weight: bold; padding: 4px 10px; border-radius: 4px;")
        btn_open.clicked.connect(self.open_file)
        header_lay.addWidget(btn_open)
        card_layout.addLayout(header_lay)

        # Shortcuts Cheatsheet Grid
        grid_lay = QGridLayout()
        grid_lay.setSpacing(6)

        shortcuts_info = [
            ("Shift + PrintScreen", "Global Desktop Snip"),
            ("Ctrl + N", "New Region Snip"),
            ("Ctrl + O", "Open Image File"),
            ("Ctrl + S", "Quick Save File"),
            ("Ctrl + C", "Copy to Clipboard"),
            ("Ctrl + Z", "Undo Action"),
        ]

        for idx, (key, desc) in enumerate(shortcuts_info):
            r, c = idx // 2, (idx % 2) * 2
            lbl_key = QLabel(key)
            lbl_key.setStyleSheet("font-weight: bold; background-color: #1E2228; border: 1px solid #3A3F4A; border-radius: 4px; padding: 2px 6px; color: #FFFFFF;")
            lbl_desc = QLabel(desc)
            lbl_desc.setStyleSheet("color: #A0A5B0;")
            grid_lay.addWidget(lbl_key, r, c)
            grid_lay.addWidget(lbl_desc, r, c + 1)

        card_layout.addLayout(grid_lay)
        parent_layout.addWidget(self.launcher_card)

    def show_launcher_mode(self):
        if hasattr(self, 'launcher_card') and self.launcher_card:
            self.launcher_card.show()
        if hasattr(self, 'mid_tools_container') and self.mid_tools_container:
            self.mid_tools_container.setVisible(False)
        if hasattr(self, 'canvas_editor') and self.canvas_editor:
            self.canvas_editor.hide()

        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
            QApplication.processEvents()

        widgets_to_update = [
            self,
            self.centralWidget() if hasattr(self, 'centralWidget') else None,
            getattr(self, 'toolbar_border_frame', None),
            getattr(self, 'toolbar_frame', None),
            getattr(self, 'launcher_card', None)
        ]
        for w in widgets_to_update:
            if w:
                w.updateGeometry()
                if w.layout():
                    w.layout().activate()

        self.resize(self.minimumSizeHint())
        self.adjustSize()
        self.center_window()
        self.showNormal()

    def show_editor_mode(self):
        if hasattr(self, 'launcher_card') and self.launcher_card:
            self.launcher_card.hide()
        if hasattr(self, 'mid_tools_container') and self.mid_tools_container:
            self.mid_tools_container.setVisible(True)
        if hasattr(self, 'canvas_editor') and self.canvas_editor:
            self.canvas_editor.show()

    def make_v_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def make_action_button(self, icon_name, slot, tooltip, icon_color):
        btn = QPushButton()
        btn.setIcon(get_qicon(icon_name, icon_color, (self.icon_size_px, self.icon_size_px)))
        btn.setIconSize(QSize(self.icon_size_px, self.icon_size_px))
        btn.setFixedSize(self.btn_size_px, self.btn_size_px)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    def center_window(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(max(0, x), max(0, y))

    def setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+N"), self, self.start_capture)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_to_clipboard)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_quick)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.save_as)
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)
        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)

    def apply_theme(self):
        theme_name = self.config.get("theme")
        if theme_name == "dark":
            self.setStyleSheet(get_dark_qss())
        else:
            self.setStyleSheet(get_light_qss())

    def load_settings(self):
        self.set_tool(self.config.get("last_tool"))
        self.set_color(self.config.get("last_color"))

    def start_capture(self):
        mode = self.cb_mode.currentText()
        try:
            fw = int(self.entry_w.text())
            fh = int(self.entry_h.text())
        except ValueError:
            fw, fh = 800, 600

        self.overlay = CaptureOverlay(self, mode=mode, fixed_width=fw, fixed_height=fh, callback=self.on_capture_complete)

    def on_capture_complete(self, pil_image):
        if pil_image:
            self.show_editor_mode()
            self.canvas_editor.set_image(pil_image)
            self.lbl_status_dims.setText(f"RESOLUTION: {pil_image.width} x {pil_image.height} PX")
            self.copy_captured_to_clipboard(pil_image)
            self.showMaximized()
        elif self.isHidden():
            self.show()
        self.activateWindow()
        self.raise_()

    def copy_captured_to_clipboard(self, pil_image):
        """Automatically copies a freshly captured snippet to the system clipboard."""
        try:
            pixmap = pil_to_qpixmap(pil_image)
            if pixmap.isNull():
                return
            cb = QGuiApplication.clipboard()
            cb.setPixmap(pixmap)
            cb.setImage(pixmap.toImage())
            self.statusBar().showMessage("Snippet copied to clipboard", 3000)
        except Exception as e:
            print(f"Error copying captured snippet to clipboard: {e}")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Image File", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if file_path:
            try:
                img = Image.open(file_path).convert("RGBA")
                self.show_editor_mode()
                self.canvas_editor.set_image(img)
                self.lbl_status_dims.setText(f"RESOLUTION: {img.width} x {img.height} PX")
                self.showMaximized()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load image:\n{e}")

    def on_crop_complete(self, w, h):
        self.lbl_status_dims.setText(f"RESOLUTION: {w} x {h} PX")
        self.lbl_status_zoom.setText(f"ZOOM: {int(round(self.canvas_editor.zoom_factor * 100))}%")

    def set_tool(self, tool_name):
        self.config.set("last_tool", tool_name)
        if self.canvas_editor.tool != tool_name:
            self.canvas_editor.set_tool(tool_name)

        is_dark = (self.config.get("theme") == "dark")
        active_color = "#FFFFFF"
        inactive_color = "#E5E7EB" if is_dark else "#333333"

        for name, btn in self.tool_buttons.items():
            icon_name = self.tool_icon_names.get(name, "pointer")
            if name == tool_name:
                btn.setChecked(True)
                btn.setIcon(get_qicon(icon_name, active_color, (self.icon_size_px, self.icon_size_px)))
            else:
                btn.setChecked(False)
                btn.setIcon(get_qicon(icon_name, inactive_color, (self.icon_size_px, self.icon_size_px)))

    def set_color(self, color_hex):
        self.config.set("last_color", color_hex)
        self.canvas_editor.set_color(color_hex)
        self.lbl_status_tool.setText(f"TOOL: {self.canvas_editor.tool.upper()} ({color_hex})")

    def choose_custom_color(self):
        col = QColorDialog.getColor(QColor(self.canvas_editor.color), self, "Select Custom Drawing Color")
        if col.isValid():
            self.set_color(col.name())

    def on_style_changed(self):
        try:
            th = int(self.cb_thickness.currentText())
            self.canvas_editor.set_thickness(th)
            self.config.set("last_thickness", th)
        except ValueError:
            pass

        mode = self.cb_fill.currentText()
        self.canvas_editor.set_fill_mode(mode)
        self.config.set("last_fill_mode", mode)

        font_fam = self.cb_font_family.currentText()
        self.canvas_editor.set_font_family(font_fam)
        self.config.set("last_font_family", font_fam)

        try:
            f_size = int(self.cb_font_size.currentText())
            self.canvas_editor.set_font_size(f_size)
            self.config.set("last_font_size", f_size)
        except ValueError:
            pass

    def on_mode_changed(self, mode):
        self.config.set("default_capture_mode", mode)

    def font_dec(self):
        try:
            curr = int(self.cb_font_size.currentText())
            new_val = max(6, curr - 2)
            self.cb_font_size.setCurrentText(str(new_val))
        except ValueError:
            pass

    def font_inc(self):
        try:
            curr = int(self.cb_font_size.currentText())
            new_val = min(72, curr + 2)
            self.cb_font_size.setCurrentText(str(new_val))
        except ValueError:
            pass

    def update_coords_status(self, x, y):
        self.lbl_status_coords.setText(f"COORDS: {x}, {y}")

    def zoom_in(self):
        self.canvas_editor.zoom_factor *= 1.15
        self.canvas_editor.scale(1.15, 1.15)
        self.lbl_status_zoom.setText(f"ZOOM: {int(round(self.canvas_editor.zoom_factor * 100))}%")

    def zoom_out(self):
        self.canvas_editor.zoom_factor *= 0.85
        self.canvas_editor.scale(0.85, 0.85)
        self.lbl_status_zoom.setText(f"ZOOM: {int(round(self.canvas_editor.zoom_factor * 100))}%")

    def undo(self):
        self.canvas_editor.undo()

    def redo(self):
        self.canvas_editor.redo()

    def has_deletable_content(self):
        """Returns True when the workspace holds a snippet or annotations to delete."""
        editor = getattr(self, 'canvas_editor', None)
        if not editor:
            return False
        if getattr(editor, 'base_image', None) is not None:
            return True
        return bool(getattr(editor, 'history', None))

    def create_delete_confirmation_box(self):
        """Builds the themed confirmation popup used before deleting a snippet."""
        box = QMessageBox(self)
        box.setWindowTitle("Delete Snippet")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Delete the captured snippet?")
        box.setInformativeText(
            "The captured image and all of its annotations will be discarded.\n"
            "This action cannot be undone."
        )
        self.btn_confirm_delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        self.btn_confirm_cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(self.btn_confirm_cancel)
        box.setEscapeButton(self.btn_confirm_cancel)
        return box

    def confirm_delete_snippet(self):
        """Asks the user to confirm deleting the captured snippet.

        The confirmation prompt is only shown when the "confirm_before_delete"
        preference is enabled in the Preferences dialog. When the preference is
        disabled (or when there is nothing to delete) True is returned right
        away so the deletion proceeds without any popup.
        """
        if not self.has_deletable_content():
            return True
        if not self.config.get("confirm_before_delete"):
            return True

        box = self.create_delete_confirmation_box()
        box.exec()
        return box.clickedButton() is self.btn_confirm_delete

    def delete_snippet(self):
        """Delete-button handler: asks for confirmation (per preferences), then clears."""
        if not self.confirm_delete_snippet():
            self.statusBar().showMessage("Delete cancelled", 2000)
            return
        self.clear_canvas()

    def clear_canvas(self):
        self.canvas_editor.clear_canvas(reset_image=True)
        self.show_launcher_mode()
        self.lbl_status_dims.setText("RESOLUTION: 0 x 0 PX")
        self.lbl_status_zoom.setText("ZOOM: 100%")
        self.lbl_status_coords.setText("COORDS: 0, 0")
        self.statusBar().showMessage("Cleared workspace and captured snippet", 3000)

    def copy_to_clipboard(self):
        baked = self.canvas_editor.get_baked_image()
        selected = [
            i for i in self.canvas_editor.scene.selectedItems()
            if i != self.canvas_editor.selection_box and i != self.canvas_editor.bg_pixmap_item
        ]
        if selected:
            try:
                rect = selected[0].sceneBoundingRect().toRect()
                x1 = max(0, rect.x())
                y1 = max(0, rect.y())
                x2 = min(baked.width, rect.x() + rect.width())
                y2 = min(baked.height, rect.y() + rect.height())
                if x2 - x1 > 2 and y2 - y1 > 2:
                    baked = baked.crop((x1, y1, x2, y2))
                    self.statusBar().showMessage("Copied selected element to clipboard", 3000)
                else:
                    self.statusBar().showMessage("Copied edited snippet to clipboard", 3000)
            except Exception:
                self.statusBar().showMessage("Copied edited snippet to clipboard", 3000)
        else:
            self.statusBar().showMessage("Copied edited snippet to clipboard", 3000)

        pixmap = pil_to_qpixmap(baked)
        cb = QGuiApplication.clipboard()
        cb.setPixmap(pixmap)
        cb.setImage(pixmap.toImage())

        self.lbl_status_path.setText("COPIED TO CLIPBOARD!")

    # Image extensions that must never be treated as part of the pattern text.
    IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")

    # Characters Windows does not allow inside a file name.
    ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    @staticmethod
    def _remove_placeholder(pattern, placeholder):
        """Removes ``placeholder`` from ``pattern`` keeping the literal text.

        Only the separators that were glued to the placeholder are tidied up,
        so ``"Capture_{datetime}"`` becomes ``"Capture"`` and
        ``"QA_{datetime}_AR"`` becomes ``"QA_AR"``, while a pattern without the
        placeholder (e.g. ``"-eso-qa5_ESO_2026.3.1+_Not_promoted_AR"``) is
        returned completely unchanged.
        """
        start = pattern.find(placeholder)
        if start == -1:
            return pattern

        end = start + len(placeholder)
        before, after = pattern[:start], pattern[end:]
        lead = re.search(r"[_-]*$", before).group(0)
        trail = re.match(r"[_-]*", after).group(0)
        head, tail = before[: len(before) - len(lead)], after[len(trail):]

        if head and tail:
            return head + (lead or trail or "_") + tail
        return head + tail

    def _resolve_index_placeholder(self, filename, ext, folder):
        """Replaces ``{index}`` with the next free counter (001, 002, ...).

        Existing files in ``folder`` that match the pattern are scanned so the
        generated name never collides with an already exported snippet.
        """
        if "{index}" not in filename:
            return filename

        prefix, suffix = filename.split("{index}", 1)
        folder = folder or self.config.get("default_save_path") or ""

        next_idx = 1
        if folder and os.path.isdir(folder):
            existing = re.compile(
                "^" + re.escape(prefix) + r"(\d+)" + re.escape(suffix) + re.escape(ext) + "$",
                re.IGNORECASE,
            )
            max_idx = 0
            try:
                for name in os.listdir(folder):
                    match = existing.match(name)
                    if match:
                        max_idx = max(max_idx, int(match.group(1)))
            except OSError:
                pass
            next_idx = max_idx + 1

        return filename.replace("{index}", f"{next_idx:03d}")

    @staticmethod
    def _make_unique_filename(filename, folder):
        """Returns ``filename`` with a numeric suffix if it already exists.

        Prevents two snippets captured within the same second (or a pattern
        without placeholders, e.g. a fixed name) from silently overwriting an
        already exported file: ``"Shot_2.png"``, ``"Shot_3.png"``, ...
        """
        if not folder:
            return filename

        target = os.path.join(folder, filename)
        if not os.path.exists(target):
            return filename

        base, ext = os.path.splitext(filename)
        counter = 2
        candidate = f"{base}_{counter}{ext}"
        while os.path.exists(os.path.join(folder, candidate)):
            counter += 1
            candidate = f"{base}_{counter}{ext}"
        return candidate

    def generate_default_filename(self, fmt=None, include_datetime=True, folder=None):
        """Generates a default filename from the configured naming pattern.

        Supported placeholders:
            {datetime} - timestamp formatted as YYYYMMDD_HHMMSS.
            {index}    - auto-incrementing counter (001, 002, ...) based on the
                         files already present in ``folder``.

        The literal text of the pattern is preserved exactly as typed in
        Preferences, so the name offered in the Save As dialog matches the
        configured "Filename Naming Pattern". Only characters that are illegal
        in Windows file names are replaced, and the format extension is
        appended once (a known image extension already present is replaced).

        A timestamp is NEVER appended automatically - it only appears in the
        name when the pattern itself contains {datetime}. A pattern such as
        "-eso-qa5_ESO_2026.3.1+_Not_promoted_AR" therefore yields exactly that
        name (plus the extension). When ``include_datetime`` is False the
        {datetime} placeholder is dropped instead of being filled in.
        """
        fmt = (fmt or self.config.get("default_format") or "png").lower()
        ext = ".jpg" if fmt in ("jpeg", "jpg") else f".{fmt}"

        pattern = (self.config.get("naming_pattern") or "").strip() or "Capture"

        if include_datetime:
            filename = pattern.replace("{datetime}", time.strftime("%Y%m%d_%H%M%S"))
        else:
            filename = self._remove_placeholder(pattern, "{datetime}")

        # Strip an image extension already present in the pattern so the
        # configured format extension is appended exactly once. Only KNOWN
        # extensions are removed - dots that belong to the name itself
        # (e.g. "ESO_2026.3.1") must survive untouched.
        for known_ext in self.IMAGE_EXTENSIONS:
            if filename.lower().endswith(known_ext):
                filename = filename[: -len(known_ext)]
                break

        filename = self._resolve_index_placeholder(filename, ext, folder)

        # Keep Windows happy: no illegal characters, no trailing dots/spaces.
        filename = self.ILLEGAL_FILENAME_CHARS.sub("_", filename).rstrip(" .")
        if not filename.strip("_- "):
            filename = "Capture"

        return self._make_unique_filename(f"{filename}{ext}", folder)

    def save_quick(self):
        if not self.canvas_editor.base_image:
            self.statusBar().showMessage("Nothing to save - capture or open a snippet first.", 4000)
            return

        dest_folder = self.config.get("default_save_path") or os.path.expanduser("~")
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder, exist_ok=True)

        fmt = (self.config.get("default_format") or "png").lower()
        filename = self.generate_default_filename(fmt, folder=dest_folder)
        full_path = os.path.join(dest_folder, filename)

        baked = self.canvas_editor.get_baked_image()
        if fmt == "jpeg":
            baked.convert("RGB").save(full_path, "JPEG")
        else:
            baked.save(full_path, fmt.upper())

        self.lbl_status_path.setText(f"QUICK SAVED: {filename}")
        self.statusBar().showMessage(f"Quick saved to {full_path}", 4000)

    def save_as(self):
        if not self.canvas_editor.base_image:
            self.statusBar().showMessage("Nothing to save - capture or open a snippet first.", 4000)
            return

        fmt = (self.config.get("default_format") or "png").lower()
        ext_filter = "PNG Image (*.png)" if fmt == "png" else "JPEG Image (*.jpg)"

        save_dir = self.config.get("default_save_path") or ""
        if save_dir and not os.path.isdir(save_dir):
            # The configured folder may have been removed/moved - recreate it so
            # the dialog can start there instead of silently dropping the path.
            try:
                os.makedirs(save_dir, exist_ok=True)
            except OSError:
                save_dir = ""

        # Pre-fill the dialog with the name produced by the "Filename Naming
        # Pattern" from Preferences (exactly as it will be written to disk) so
        # the configured pattern is always visible and can still be renamed.
        default_filename = self.generate_default_filename(fmt, folder=save_dir)
        default_path = os.path.join(save_dir, default_filename) if save_dir else default_filename

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Snippet As", default_path, f"{ext_filter};;All Files (*.*)"
        )
        if file_path:
            baked = self.canvas_editor.get_baked_image()
            if file_path.lower().endswith(".jpg") or file_path.lower().endswith(".jpeg"):
                baked.convert("RGB").save(file_path, "JPEG")
            else:
                baked.save(file_path, "PNG")

            self.lbl_status_path.setText(f"SAVED: {os.path.basename(file_path)}")
            self.statusBar().showMessage(f"Saved snippet to {file_path}", 4000)

    def open_collage_editor(self):
        dialog = CollageEditorDialog(self, theme_colors={"theme_name": self.config.get("theme")}, initial_image=self.canvas_editor.base_image, result_callback=self.on_capture_complete, root_window=self)
        dialog.exec()

    def open_settings_dialog(self):
        dialog = PreferencesDialog(self, self.config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_theme()
            self.lbl_status_path.setText(f"SAVE DEST: {self.config.get('default_save_path')}")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


class PreferencesDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.setWindowTitle("Preferences Configuration")
        self.config = config
        self.resize(520, 410)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Theme
        t_layout = QHBoxLayout()
        t_layout.addWidget(QLabel("Interface Theme:"))
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["light", "dark"])
        self.cb_theme.setCurrentText(self.config.get("theme"))
        t_layout.addWidget(self.cb_theme)
        layout.addLayout(t_layout)

        # Save Folder
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Default Save Folder:"))
        self.lbl_path = QLabel(self.config.get("default_save_path"))
        path_layout.addWidget(self.lbl_path)

        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        # Naming Pattern
        pattern_layout = QHBoxLayout()
        pattern_layout.addWidget(QLabel("Filename Naming Pattern:"))
        self.entry_pattern = QLineEdit(self.config.get("naming_pattern") or "Capture_{datetime}")
        self.entry_pattern.setPlaceholderText("Capture_{datetime}  -  {datetime} = timestamp, {index} = counter")
        self.entry_pattern.setToolTip(
            "The name is used exactly as typed - no timestamp is added unless the "
            "pattern itself contains {datetime}.\n"
            "{datetime} inserts YYYYMMDD_HHMMSS and {index} inserts an "
            "auto-incrementing counter (001, 002, ...)."
        )
        pattern_layout.addWidget(self.entry_pattern)
        layout.addLayout(pattern_layout)

        # Format
        fmt_layout = QHBoxLayout()
        fmt_layout.addWidget(QLabel("Default Format:"))
        self.cb_format = QComboBox()
        self.cb_format.addItems(["PNG", "JPEG"])
        self.cb_format.setCurrentText(self.config.get("default_format"))
        fmt_layout.addWidget(self.cb_format)
        layout.addLayout(fmt_layout)

        # Delete Confirmation Behaviour
        self.chk_confirm_delete = QCheckBox("Ask for confirmation before deleting the captured snippet")
        self.chk_confirm_delete.setChecked(bool(self.config.get("confirm_before_delete")))
        self.chk_confirm_delete.setToolTip(
            "Enabled: clicking the delete button shows a confirmation popup.\n"
            "Disabled: the captured snippet is deleted immediately."
        )
        layout.addWidget(self.chk_confirm_delete)

        # Actions
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self.save_settings)
        btn_layout.addWidget(btn_save)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder", self.config.get("default_save_path"))
        if folder:
            self.lbl_path.setText(folder)

    def save_settings(self):
        self.config.set("theme", self.cb_theme.currentText())
        self.config.set("default_save_path", self.lbl_path.text())
        self.config.set("naming_pattern", self.entry_pattern.text())
        self.config.set("default_format", self.cb_format.currentText())
        self.config.set("confirm_before_delete", self.chk_confirm_delete.isChecked())
        self.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = SnippingToolApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
