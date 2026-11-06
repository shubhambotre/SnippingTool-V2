import os
import time
from PIL import Image, ImageDraw, ImageOps, ImageFont, ImageEnhance
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QSlider, QFileDialog, QMessageBox, QFrame, QScrollArea, QWidget,
    QCheckBox, QRadioButton, QButtonGroup, QColorDialog, QGroupBox, QSplitter
)

from capture import CaptureOverlay

def pil_to_qpixmap(pil_img):
    """Converts a PIL RGBA Image to a PySide6 QPixmap."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


# ---------------------------------------------------------------------------
# Layout templates — normalized cell bounding boxes (nx, ny, nw, nh)
# ---------------------------------------------------------------------------
TEMPLATES = {
    "2 x 1":    [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)],
    "1 x 2":    [(0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)],
    "2 x 2":    [
        (0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5),
    ],
    "3 x 1":    [(i / 3.0, 0.0, 1 / 3.0, 1.0) for i in range(3)],
    "1 x 3":    [(0.0, i / 3.0, 1.0, 1 / 3.0) for i in range(3)],
    "3 x 2":    [(j / 3.0, i / 2.0, 1 / 3.0, 0.5) for i in range(2) for j in range(3)],
    "2 x 3":    [(j / 2.0, i / 3.0, 0.5, 1 / 3.0) for i in range(3) for j in range(2)],
    "Focus L":  [
        (0.0, 0.0, 0.60, 1.0),
        (0.60, 0.0, 0.40, 0.5),
        (0.60, 0.5, 0.40, 0.5),
    ],
    "Focus R":  [
        (0.0, 0.0, 0.40, 0.5),
        (0.0, 0.5, 0.40, 0.5),
        (0.40, 0.0, 0.60, 1.0),
    ],
}

DEFAULT_OUT_W = 1920
DEFAULT_OUT_H = 1080


class CollageCell:
    """Holds the transformation, photo editing, and image state for one cell slot in the collage."""

    def __init__(self, nx, ny, nw, nh):
        self.nx = float(nx)
        self.ny = float(ny)
        self.nw = float(nw)
        self.nh = float(nh)
        self.image = None          # PIL Image or None
        self.fit = "cover"         # "cover" | "contain" | "stretch"
        self.rotation = 0          # 0 | 90 | 180 | 270
        self.flip_h = False
        self.flip_v = False
        self.pan_x = 0.5           # 0.0 (Left) to 1.0 (Right), default 0.5
        self.pan_y = 0.5           # 0.0 (Top) to 1.0 (Bottom), default 0.5
        self.brightness = 0        # -100 to +100
        self.contrast = 0          # -100 to +100
        self.filter_type = "Original" # Original | Grayscale | Sepia | Vivid | Cool | Warm

    def pixel_rect(self, out_w, out_h, gap):
        """Compute inset pixel rect (x1, y1, x2, y2) for this cell."""
        half = gap // 2
        x1 = round(self.nx * out_w) + half
        y1 = round(self.ny * out_h) + half
        x2 = round((self.nx + self.nw) * out_w) - half
        y2 = round((self.ny + self.nh) * out_h) - half
        return x1, y1, max(x1 + 1, x2), max(y1 + 1, y2)

    def render_into(self, canvas_img, out_w, out_h, gap, is_selected=False, corner_radius=0, draw_selection=True):
        """Paste cell contents into canvas_img at the computed position."""
        x1, y1, x2, y2 = self.pixel_rect(out_w, out_h, gap)
        cw, ch = x2 - x1, y2 - y1
        if cw <= 0 or ch <= 0:
            return

        if self.image is None:
            placeholder = Image.new("RGBA", (cw, ch), (40, 44, 52, 255))
            d = ImageDraw.Draw(placeholder)
            d.line([(0, 0), (cw - 1, ch - 1)], fill=(70, 75, 85, 200), width=2)
            d.line([(cw - 1, 0), (0, ch - 1)], fill=(70, 75, 85, 200), width=2)
            d.rectangle([0, 0, cw - 1, ch - 1], outline=(90, 95, 105), width=2)

            icon_r = min(cw // 2, ch // 2, 22)
            cx_i, cy_i = cw // 2, ch // 2
            d.line([(cx_i - icon_r, cy_i), (cx_i + icon_r, cy_i)], fill=(160, 165, 175), width=3)
            d.line([(cx_i, cy_i - icon_r), (cx_i, cy_i + icon_r)], fill=(160, 165, 175), width=3)

            if is_selected and draw_selection:
                d.rectangle([0, 0, cw - 1, ch - 1], outline=(0, 229, 255), width=4)

            canvas_img.paste(placeholder, (x1, y1), placeholder)
            return

        # Prepare transformed copy of cell image
        img = self.image.convert("RGBA")

        # 1. Photo Adjustments (Brightness & Contrast)
        if self.brightness != 0:
            b_factor = max(0.0, 1.0 + self.brightness / 100.0)
            img = ImageEnhance.Brightness(img).enhance(b_factor)
        if self.contrast != 0:
            c_factor = max(0.0, 1.0 + self.contrast / 100.0)
            img = ImageEnhance.Contrast(img).enhance(c_factor)

        # 2. Filters
        if self.filter_type == "Grayscale":
            gray = ImageOps.grayscale(img).convert("RGBA")
            img = gray
        elif self.filter_type == "Sepia":
            gray = ImageOps.grayscale(img)
            sepia = ImageOps.colorize(gray, "#2E1F0F", "#F5E0C3").convert("RGBA")
            img = sepia
        elif self.filter_type == "Vivid":
            img = ImageEnhance.Color(img).enhance(1.8)
        elif self.filter_type == "Cool":
            r, g, b, a = img.split()
            b = b.point(lambda i: min(255, int(i * 1.25)))
            img = Image.merge("RGBA", (r, g, b, a))
        elif self.filter_type == "Warm":
            r, g, b, a = img.split()
            r = r.point(lambda i: min(255, int(i * 1.25)))
            img = Image.merge("RGBA", (r, g, b, a))

        # 3. Rotation & Mirroring
        if self.rotation:
            img = img.rotate(-self.rotation, expand=True)
        if self.flip_h:
            img = ImageOps.mirror(img)
        if self.flip_v:
            img = ImageOps.flip(img)

        iw, ih = img.size
        if iw == 0 or ih == 0:
            return

        cell_tile = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

        if self.fit == "stretch":
            cell_tile = img.resize((cw, ch), Image.LANCZOS)

        elif self.fit == "contain":
            scale = min(cw / iw, ch / ih)
            nw_i = max(1, int(iw * scale))
            nh_i = max(1, int(ih * scale))
            img_r = img.resize((nw_i, nh_i), Image.LANCZOS)
            extra_w = max(0, cw - nw_i)
            extra_h = max(0, ch - nh_i)
            px = int(extra_w * self.pan_x)
            py = int(extra_h * self.pan_y)
            cell_tile.paste(img_r, (px, py), img_r)

        else:  # cover (default)
            scale = max(cw / iw, ch / ih)
            nw_i = max(1, int(iw * scale))
            nh_i = max(1, int(ih * scale))
            img_r = img.resize((nw_i, nh_i), Image.LANCZOS)
            extra_w = max(0, nw_i - cw)
            extra_h = max(0, nh_i - ch)
            crop_x = int(extra_w * self.pan_x)
            crop_y = int(extra_h * self.pan_y)
            cell_tile = img_r.crop((crop_x, crop_y, crop_x + cw, crop_y + ch))

        # 4. Corner Radius Masking
        if corner_radius > 0:
            mask = Image.new("L", (cw, ch), 0)
            d_mask = ImageDraw.Draw(mask)
            d_mask.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=corner_radius, fill=255)
            canvas_img.paste(cell_tile, (x1, y1), mask)
        else:
            canvas_img.paste(cell_tile, (x1, y1), cell_tile)

        # Draw selection highlight (ONLY when draw_selection is True!)
        if is_selected and draw_selection:
            d_sel = ImageDraw.Draw(canvas_img)
            if corner_radius > 0:
                d_sel.rounded_rectangle([x1, y1, x2 - 1, y2 - 1], radius=corner_radius, outline=(0, 229, 255), width=4)
            else:
                d_sel.rectangle([x1, y1, x2 - 1, y2 - 1], outline=(0, 229, 255), width=4)


class CollageEditorDialog(QDialog):
    """Full PySide6 Photo Collage Editor Dialog with interactive cell customization."""

    def __init__(self, parent, theme_colors, initial_image=None, result_callback=None, root_window=None):
        super().__init__(parent)
        self.setWindowTitle("Photo Collage Editor")
        self.tc = theme_colors
        self.initial_image = initial_image
        self.result_callback = result_callback
        self.root_window = root_window

        self.current_template = "1 x 2"
        self.gap_val = 8
        self.corner_radius_val = 6
        self.out_w_val = DEFAULT_OUT_W
        self.out_h_val = DEFAULT_OUT_H
        self.bg_color_val = "#18191A" if self.tc.get("theme_name") == "dark" else "#EFEFEF"

        self.cells = []
        self.selected_idx = None

        self.resize(1140, 740)
        self.setup_ui()
        self.apply_template(self.current_template)

        if self.initial_image and self.cells:
            self.cells[0].image = self.initial_image.copy()
            self.selected_idx = 0
            self.update_cell_panel()
            self.update_preview()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        # -------------------------------------------------------------------
        # TOP CONFIGURATION BAR
        # -------------------------------------------------------------------
        top_bar = QHBoxLayout()

        top_bar.addWidget(QLabel("Template:"))
        self.cb_template = QComboBox()
        self.cb_template.addItems(list(TEMPLATES.keys()))
        self.cb_template.currentTextChanged.connect(self.apply_template)
        top_bar.addWidget(self.cb_template)

        top_bar.addWidget(QLabel("Gap:"))
        self.lbl_gap_val = QLabel(f"{self.gap_val} px")
        self.lbl_gap_val.setFixedWidth(36)
        self.slider_gap = QSlider(Qt.Orientation.Horizontal)
        self.slider_gap.setRange(0, 32)
        self.slider_gap.setValue(self.gap_val)
        self.slider_gap.valueChanged.connect(self.on_gap_changed)
        top_bar.addWidget(self.slider_gap)
        top_bar.addWidget(self.lbl_gap_val)

        top_bar.addWidget(QLabel("Corners:"))
        self.lbl_corner_val = QLabel(f"{self.corner_radius_val} px")
        self.lbl_corner_val.setFixedWidth(36)
        self.slider_corner = QSlider(Qt.Orientation.Horizontal)
        self.slider_corner.setRange(0, 30)
        self.slider_corner.setValue(self.corner_radius_val)
        self.slider_corner.valueChanged.connect(self.on_corner_changed)
        top_bar.addWidget(self.slider_corner)
        top_bar.addWidget(self.lbl_corner_val)

        top_bar.addWidget(QLabel("Width:"))
        self.spin_w = QSpinBox()
        self.spin_w.setRange(400, 3840)
        self.spin_w.setValue(self.out_w_val)
        self.spin_w.valueChanged.connect(self.on_size_changed)
        top_bar.addWidget(self.spin_w)

        top_bar.addWidget(QLabel("Height:"))
        self.spin_h = QSpinBox()
        self.spin_h.setRange(300, 2160)
        self.spin_h.setValue(self.out_h_val)
        self.spin_h.valueChanged.connect(self.on_size_changed)
        top_bar.addWidget(self.spin_h)

        top_bar.addWidget(QLabel("BG Color:"))
        self.btn_bg_color = QPushButton()
        self.btn_bg_color.setFixedSize(28, 24)
        self.btn_bg_color.setStyleSheet(f"background-color: {self.bg_color_val}; border: 1px solid #777777; border-radius: 4px;")
        self.btn_bg_color.clicked.connect(self.choose_bg_color)
        top_bar.addWidget(self.btn_bg_color)

        self.lbl_fill_info = QLabel("0 / 0 filled")
        self.lbl_fill_info.setStyleSheet("font-weight: bold; color: #00E5FF;")
        top_bar.addStretch()
        top_bar.addWidget(self.lbl_fill_info)

        main_layout.addLayout(top_bar)

        # -------------------------------------------------------------------
        # TOP IMAGE PLANNING & SLOT ADJUSTMENTS BAR (Above Preview Canvas)
        # -------------------------------------------------------------------
        self.panel_cell_opts = QGroupBox("Selected Slot Photo Planning & Adjustments")
        cell_main_layout = QVBoxLayout(self.panel_cell_opts)
        cell_main_layout.setContentsMargins(8, 6, 8, 6)

        self.lbl_cell_hint = QLabel("Select a cell slot in the preview canvas to edit image positioning, filters, adjustments, or capture a screen area.")
        self.lbl_cell_hint.setWordWrap(True)
        self.lbl_cell_hint.setStyleSheet("color: #888888; font-style: italic;")
        cell_main_layout.addWidget(self.lbl_cell_hint)

        self.opts_container = QWidget()
        opts_layout = QHBoxLayout(self.opts_container)
        opts_layout.setContentsMargins(0, 0, 0, 0)
        opts_layout.setSpacing(12)

        # 1. Slot Image Actions
        act_box = QGroupBox("Image Source")
        act_layout = QHBoxLayout(act_box)
        
        btn_load = QPushButton("📁 Load File")
        btn_load.clicked.connect(self.load_image_for_selected)
        act_layout.addWidget(btn_load)

        btn_snip = QPushButton("✂️ Snip Region")
        btn_snip.clicked.connect(self.snip_into_selected)
        act_layout.addWidget(btn_snip)

        btn_replace = QPushButton("🔄 Replace")
        btn_replace.clicked.connect(self.load_image_for_selected)
        act_layout.addWidget(btn_replace)

        btn_clear = QPushButton("🗑️ Clear")
        btn_clear.clicked.connect(self.clear_selected_slot)
        act_layout.addWidget(btn_clear)

        opts_layout.addWidget(act_box)

        # 2. Photo Adjustments & Filters
        filter_box = QGroupBox("Photo Adjustments & Filter")
        filter_layout = QHBoxLayout(filter_box)

        filter_layout.addWidget(QLabel("Filter:"))
        self.cb_filter = QComboBox()
        self.cb_filter.addItems(["Original", "Grayscale", "Sepia", "Vivid", "Cool", "Warm"])
        self.cb_filter.currentTextChanged.connect(self.on_filter_changed)
        filter_layout.addWidget(self.cb_filter)

        filter_layout.addWidget(QLabel("Bright:"))
        self.lbl_bright_val = QLabel("0")
        self.lbl_bright_val.setFixedWidth(24)
        self.slider_bright = QSlider(Qt.Orientation.Horizontal)
        self.slider_bright.setRange(-100, 100)
        self.slider_bright.setValue(0)
        self.slider_bright.setFixedWidth(80)
        self.slider_bright.valueChanged.connect(self.on_brightness_changed)
        filter_layout.addWidget(self.slider_bright)
        filter_layout.addWidget(self.lbl_bright_val)

        filter_layout.addWidget(QLabel("Contrast:"))
        self.lbl_contrast_val = QLabel("0")
        self.lbl_contrast_val.setFixedWidth(24)
        self.slider_contrast = QSlider(Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(-100, 100)
        self.slider_contrast.setValue(0)
        self.slider_contrast.setFixedWidth(80)
        self.slider_contrast.valueChanged.connect(self.on_contrast_changed)
        filter_layout.addWidget(self.slider_contrast)
        filter_layout.addWidget(self.lbl_contrast_val)

        opts_layout.addWidget(filter_box)

        # 3. Fit Mode & Orientation
        orient_box = QGroupBox("Fit & Orientation")
        orient_layout = QHBoxLayout(orient_box)

        orient_layout.addWidget(QLabel("Fit:"))
        self.cb_fit = QComboBox()
        self.cb_fit.addItems(["cover", "contain", "stretch"])
        self.cb_fit.currentTextChanged.connect(self.on_cell_property_changed)
        orient_layout.addWidget(self.cb_fit)

        orient_layout.addWidget(QLabel("Rot:"))
        self.cb_rot = QComboBox()
        self.cb_rot.addItems(["0°", "90°", "180°", "270°"])
        self.cb_rot.currentTextChanged.connect(self.on_cell_property_changed)
        orient_layout.addWidget(self.cb_rot)

        self.chk_flip_h = QCheckBox("Flip H")
        self.chk_flip_h.stateChanged.connect(self.on_cell_property_changed)
        self.chk_flip_v = QCheckBox("Flip V")
        self.chk_flip_v.stateChanged.connect(self.on_cell_property_changed)
        orient_layout.addWidget(self.chk_flip_h)
        orient_layout.addWidget(self.chk_flip_v)

        opts_layout.addWidget(orient_box)

        # 4. Vertical Panning & Alignment
        pan_box = QGroupBox("Vertical Alignment & Position")
        pan_layout = QHBoxLayout(pan_box)

        btn_top = QPushButton("⬆️ Top")
        btn_top.setToolTip("Align Image to Top Header")
        btn_top.clicked.connect(lambda: self.set_pan_y(0.0))
        pan_layout.addWidget(btn_top)

        btn_center = QPushButton("↕️ Center")
        btn_center.setToolTip("Align Image to Center")
        btn_center.clicked.connect(lambda: self.set_pan_y(0.5))
        pan_layout.addWidget(btn_center)

        btn_bottom = QPushButton("⬇️ Bottom")
        btn_bottom.setToolTip("Align Image to Bottom Footer")
        btn_bottom.clicked.connect(lambda: self.set_pan_y(1.0))
        pan_layout.addWidget(btn_bottom)

        pan_layout.addWidget(QLabel("Pos Y:"))
        self.slider_pan_y = QSlider(Qt.Orientation.Horizontal)
        self.slider_pan_y.setRange(0, 100)
        self.slider_pan_y.setValue(50)
        self.slider_pan_y.setFixedWidth(80)
        self.slider_pan_y.valueChanged.connect(self.on_cell_property_changed)
        pan_layout.addWidget(self.slider_pan_y)

        opts_layout.addWidget(pan_box)

        cell_main_layout.addWidget(self.opts_container)
        self.opts_container.setVisible(False)

        main_layout.addWidget(self.panel_cell_opts)

        # -------------------------------------------------------------------
        # CENTER PREVIEW CANVAS (Below Planning Bar)
        # -------------------------------------------------------------------
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("background-color: #121212; border: 1px solid #333333; border-radius: 6px;")
        self.lbl_preview.mousePressEvent = self.on_preview_clicked
        main_layout.addWidget(self.lbl_preview, 1)

        # -------------------------------------------------------------------
        # BOTTOM DIALOG ACTIONS
        # -------------------------------------------------------------------
        bottom_bar = QHBoxLayout()

        btn_send_canvas = QPushButton("✓ Send to Canvas Editor")
        btn_send_canvas.setStyleSheet("background-color: #005FB8; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;")
        btn_send_canvas.clicked.connect(self.send_to_canvas)
        bottom_bar.addWidget(btn_send_canvas)

        btn_save = QPushButton("💾 Export to File")
        btn_save.clicked.connect(self.export_file)
        bottom_bar.addWidget(btn_save)

        btn_copy = QPushButton("📋 Copy to Clipboard")
        btn_copy.clicked.connect(self.copy_to_clipboard)
        bottom_bar.addWidget(btn_copy)

        bottom_bar.addStretch()

        btn_close = QPushButton("Cancel")
        btn_close.clicked.connect(self.reject)
        bottom_bar.addWidget(btn_close)

        main_layout.addLayout(bottom_bar)

    def apply_template(self, template_name):
        self.current_template = template_name
        coords = TEMPLATES.get(template_name, TEMPLATES["1 x 2"])

        old_images = [cell.image for cell in self.cells if cell.image is not None]
        self.cells = [CollageCell(nx, ny, nw, nh) for nx, ny, nw, nh in coords]

        for i, img in enumerate(old_images):
            if i < len(self.cells):
                self.cells[i].image = img

        self.selected_idx = 0 if self.cells else None
        self.update_cell_panel()
        self.update_preview()

    def on_gap_changed(self, val):
        self.gap_val = val
        self.lbl_gap_val.setText(f"{val} px")
        self.update_preview()

    def on_corner_changed(self, val):
        self.corner_radius_val = val
        self.lbl_corner_val.setText(f"{val} px")
        self.update_preview()

    def on_size_changed(self):
        self.out_w_val = self.spin_w.value()
        self.out_h_val = self.spin_h.value()
        self.update_preview()

    def choose_bg_color(self):
        col = QColorDialog.getColor(QColor(self.bg_color_val), self, "Select Collage Background Color")
        if col.isValid():
            self.bg_color_val = col.name()
            self.btn_bg_color.setStyleSheet(f"background-color: {self.bg_color_val}; border: 1px solid #777777; border-radius: 4px;")
            self.update_preview()

    def on_preview_clicked(self, event):
        pos = event.position().toPoint()
        lbl_w = self.lbl_preview.width()
        lbl_h = self.lbl_preview.height()

        pix = self.lbl_preview.pixmap()
        if not pix or pix.isNull():
            return

        pw = pix.width()
        ph = pix.height()
        off_x = (lbl_w - pw) // 2
        off_y = (lbl_h - ph) // 2

        click_x = pos.x() - off_x
        click_y = pos.y() - off_y
        if click_x < 0 or click_y < 0 or click_x >= pw or click_y >= ph:
            return

        norm_x = click_x / float(pw)
        norm_y = click_y / float(ph)

        for idx, cell in enumerate(self.cells):
            if cell.nx <= norm_x <= (cell.nx + cell.nw) and cell.ny <= norm_y <= (cell.ny + cell.nh):
                self.selected_idx = idx
                self.update_cell_panel()
                self.update_preview()
                break

    def update_cell_panel(self):
        if self.selected_idx is None or self.selected_idx >= len(self.cells):
            self.opts_container.setVisible(False)
            self.lbl_cell_hint.setVisible(True)
            self.panel_cell_opts.setTitle("Selected Cell Properties")
            return

        cell = self.cells[self.selected_idx]
        self.opts_container.setVisible(True)
        self.lbl_cell_hint.setVisible(False)
        self.panel_cell_opts.setTitle(f"Selected Cell #{self.selected_idx + 1} Properties")

        try:
            self.cb_fit.blockSignals(True)
            self.cb_rot.blockSignals(True)
            self.chk_flip_h.blockSignals(True)
            self.chk_flip_v.blockSignals(True)
            if hasattr(self, 'slider_pan_x'):
                self.slider_pan_x.blockSignals(True)
                self.slider_pan_y.blockSignals(True)
            self.cb_filter.blockSignals(True)
            self.slider_bright.blockSignals(True)
            self.slider_contrast.blockSignals(True)

            self.cb_fit.setCurrentText(cell.fit)
            rot_str = f"{cell.rotation}°"
            self.cb_rot.setCurrentText(rot_str if rot_str in ["0°", "90°", "180°", "270°"] else "0°")
            self.chk_flip_h.setChecked(cell.flip_h)
            self.chk_flip_v.setChecked(cell.flip_v)
            if hasattr(self, 'slider_pan_x'):
                self.slider_pan_x.setValue(int(cell.pan_x * 100))
                self.slider_pan_y.setValue(int(cell.pan_y * 100))

            self.cb_filter.setCurrentText(cell.filter_type)
            self.slider_bright.setValue(cell.brightness)
            self.lbl_bright_val.setText(str(cell.brightness))
            self.slider_contrast.setValue(cell.contrast)
            self.lbl_contrast_val.setText(str(cell.contrast))

            self.cb_fit.blockSignals(False)
            self.cb_rot.blockSignals(False)
            self.chk_flip_h.blockSignals(False)
            self.chk_flip_v.blockSignals(False)
            if hasattr(self, 'slider_pan_x'):
                self.slider_pan_x.blockSignals(False)
                self.slider_pan_y.blockSignals(False)
            self.cb_filter.blockSignals(False)
            self.slider_bright.blockSignals(False)
            self.slider_contrast.blockSignals(False)
        except RuntimeError:
            pass

    def on_filter_changed(self, text):
        if self.selected_idx is not None and self.selected_idx < len(self.cells):
            self.cells[self.selected_idx].filter_type = text
            self.update_preview()

    def on_brightness_changed(self, val):
        if self.selected_idx is not None and self.selected_idx < len(self.cells):
            self.cells[self.selected_idx].brightness = val
            self.lbl_bright_val.setText(str(val))
            self.update_preview()

    def on_contrast_changed(self, val):
        if self.selected_idx is not None and self.selected_idx < len(self.cells):
            self.cells[self.selected_idx].contrast = val
            self.lbl_contrast_val.setText(str(val))
            self.update_preview()

    def set_pan_y(self, val):
        if self.selected_idx is not None and self.selected_idx < len(self.cells):
            self.cells[self.selected_idx].pan_y = val
            if hasattr(self, 'slider_pan_y'):
                self.slider_pan_y.blockSignals(True)
                self.slider_pan_y.setValue(int(val * 100))
                self.slider_pan_y.blockSignals(False)
            self.update_preview()

    def on_cell_property_changed(self):
        if self.selected_idx is None or self.selected_idx >= len(self.cells):
            return
        cell = self.cells[self.selected_idx]
        cell.fit = self.cb_fit.currentText()

        rot_txt = self.cb_rot.currentText().replace("°", "")
        try:
            cell.rotation = int(rot_txt)
        except ValueError:
            cell.rotation = 0

        cell.flip_h = self.chk_flip_h.isChecked()
        cell.flip_v = self.chk_flip_v.isChecked()
        if hasattr(self, 'slider_pan_x'):
            cell.pan_x = self.slider_pan_x.value() / 100.0
            cell.pan_y = self.slider_pan_y.value() / 100.0

        self.update_preview()

    def load_image_for_selected(self):
        if self.selected_idx is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Image for Slot", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if file_path:
            try:
                img = Image.open(file_path).convert("RGBA")
                self.cells[self.selected_idx].image = img
                self.update_preview()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load image:\n{e}")

    def snip_into_selected(self):
        if self.selected_idx is None:
            return

        # Hide collage dialog and main application window to prevent shadow artifacts
        self.setWindowOpacity(0.0)
        self.hide()
        if self.root_window:
            self.root_window.setWindowOpacity(0.0)
            self.root_window.hide()

        def on_snip_complete(captured_img):
            if self.root_window:
                self.root_window.setWindowOpacity(1.0)
                self.root_window.show()

            self.setWindowOpacity(1.0)
            self.show()
            self.activateWindow()
            self.raise_()

            if captured_img:
                self.cells[self.selected_idx].image = captured_img
                self.update_preview()

        target_main = self.root_window if self.root_window else self
        self.snip_overlay = CaptureOverlay(target_main, mode="free", callback=on_snip_complete)

    def clear_selected_slot(self):
        if self.selected_idx is not None and self.selected_idx < len(self.cells):
            self.cells[self.selected_idx].image = None
            self.update_preview()

    def get_baked_collage_image(self, draw_selection=False):
        """Generates the full-res RGBA collage PIL Image without selection highlights."""
        out_w = self.out_w_val
        out_h = self.out_h_val
        bg_col = QColor(self.bg_color_val)
        bg_rgba = (bg_col.red(), bg_col.green(), bg_col.blue(), 255)

        collage = Image.new("RGBA", (out_w, out_h), bg_rgba)
        for idx, cell in enumerate(self.cells):
            is_sel = (idx == self.selected_idx)
            cell.render_into(collage, out_w, out_h, self.gap_val, is_selected=is_sel, corner_radius=self.corner_radius_val, draw_selection=draw_selection)
        return collage

    def update_preview(self):
        # Render canvas preview image with selection border
        collage = self.get_baked_collage_image(draw_selection=True)

        filled_cnt = sum(1 for c in self.cells if c.image is not None)
        self.lbl_fill_info.setText(f"{filled_cnt} / {len(self.cells)} slots filled")

        pix = pil_to_qpixmap(collage)
        lbl_w = max(400, self.lbl_preview.width() - 10)
        lbl_h = max(300, self.lbl_preview.height() - 10)
        scaled_pix = pix.scaled(lbl_w, lbl_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.lbl_preview.setPixmap(scaled_pix)

    def send_to_canvas(self):
        collage = self.get_baked_collage_image(draw_selection=False)
        if self.result_callback:
            self.result_callback(collage)
        elif self.root_window and hasattr(self.root_window, 'canvas_editor'):
            self.root_window.canvas_editor.set_image(collage)
        self.accept()

    def export_file(self):
        collage = self.get_baked_collage_image(draw_selection=False)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Collage Image", "Collage.png", "PNG Image (*.png);;JPEG Image (*.jpg)"
        )
        if file_path:
            try:
                if file_path.lower().endswith(".jpg") or file_path.lower().endswith(".jpeg"):
                    collage.convert("RGB").save(file_path, "JPEG", quality=95)
                else:
                    collage.save(file_path, "PNG")
                QMessageBox.information(self, "Success", f"Collage exported successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save collage:\n{e}")

    def copy_to_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        collage = self.get_baked_collage_image(draw_selection=False)
        pixmap = pil_to_qpixmap(collage)
        cb = QGuiApplication.clipboard()
        cb.setPixmap(pixmap)
        cb.setImage(pixmap.toImage())
        QMessageBox.information(self, "Copied", "Collage copied to clipboard!")
