import sys
import time
import os
import ctypes
from PIL import Image, ImageGrab, ImageEnhance
from PySide6.QtCore import Qt, QRect, QPoint, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QImage, QCursor, QKeySequence, QBrush
from PySide6.QtWidgets import QWidget, QApplication, QMainWindow

def pil_to_qpixmap(pil_img):
    """Converts a PIL RGBA Image to a PySide6 QPixmap."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)

def qimage_to_pil(qimg):
    """Converts a PySide6 QImage to a PIL Image."""
    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    width = qimg.width()
    height = qimg.height()
    ptr = qimg.constBits()
    bpl = qimg.bytesPerLine()
    data = bytes(ptr)
    return Image.frombytes("RGBA", (width, height), data, "raw", "RGBA", bpl, 1)


class _ScreenOverlay(QWidget):
    """Fullscreen snip overlay covering exactly ONE monitor, showing only that monitor's pixels."""
    HANDLE_NONE = 0
    HANDLE_NW = 1
    HANDLE_N = 2
    HANDLE_NE = 3
    HANDLE_E = 4
    HANDLE_SE = 5
    HANDLE_S = 6
    HANDLE_SW = 7
    HANDLE_W = 8

    def __init__(self, controller, screen, image, mode="free", fixed_width=800, fixed_height=600):
        super().__init__(None)
        self.controller = controller
        self.screen_ref = screen
        self.mode = mode
        self.fixed_width = fixed_width
        self.fixed_height = fixed_height

        # Image of this monitor only (physical pixels)
        self.original_image = image
        self.original_pixmap = pil_to_qpixmap(image)
        self.darkened_image = ImageEnhance.Brightness(image).enhance(0.4)
        self.darkened_pixmap = pil_to_qpixmap(self.darkened_image)

        self.start_pos = None
        self.current_pos = None
        self.crop_rect = None
        self.is_selecting = False
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        self.start_crop_rect = None

        self.confirm_btn_rect = None
        self.cancel_btn_rect = None

        self.hud_color = QColor("#00E5FF")
        self.hud_bg = QColor("#0E1013")

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)

        # Place this overlay on its own monitor
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.setGeometry(screen.geometry())

    def cursor_on_this_screen(self):
        return QApplication.screenAt(QCursor.pos()) is self.screen_ref

    def clear_selection(self):
        self.start_pos = None
        self.current_pos = None
        self.crop_rect = None
        self.is_selecting = False
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        self.start_crop_rect = None
        self.confirm_btn_rect = None
        self.update()

    def _clamp_to_widget(self, pos):
        return QPoint(max(0, min(pos.x(), self.width() - 1)),
                      max(0, min(pos.y(), self.height() - 1)))

    def enterEvent(self, event):
        # Give keyboard focus (Esc / Enter) to the monitor under the cursor
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self.controller.notify_hover(self)
        super().enterEvent(event)

    def _get_scale_factors(self):
        sw = max(1, self.width())
        sh = max(1, self.height())
        scale_x = self.original_image.width / float(sw)
        scale_y = self.original_image.height / float(sh)
        return scale_x, scale_y

    def get_crop_handle_rects(self):
        if not self.crop_rect or self.crop_rect.width() <= 0:
            return {}
        r = self.crop_rect
        hs = 10
        h_half = hs // 2
        x0, y0 = r.x(), r.y()
        x1, y1 = r.x() + r.width() // 2, r.y() + r.height() // 2
        x2, y2 = r.x() + r.width(), r.y() + r.height()

        return {
            self.HANDLE_NW: QRect(x0 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_N:  QRect(x1 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_NE: QRect(x2 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_E:  QRect(x2 - h_half, y1 - h_half, hs, hs),
            self.HANDLE_SE: QRect(x2 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_S:  QRect(x1 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_SW: QRect(x0 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_W:  QRect(x0 - h_half, y1 - h_half, hs, hs),
        }

    def handle_at(self, pos):
        for handle, rect in self.get_crop_handle_rects().items():
            if rect.contains(pos):
                return handle
        return self.HANDLE_NONE

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw darkened background of this monitor
        painter.drawPixmap(self.rect(), self.darkened_pixmap)

        mouse_pos = self.mapFromGlobal(QCursor.pos())
        cx, cy = mouse_pos.x(), mouse_pos.y()
        cursor_here = self.cursor_on_this_screen()

        # Determine current selection bounding box
        if self.mode == "fixed":
            if cursor_here:
                w, h = self.fixed_width, self.fixed_height
                sw, sh = self.width(), self.height()
                x1 = max(0, min(cx - w // 2, sw - w))
                y1 = max(0, min(cy - h // 2, sh - h))
                self.crop_rect = QRect(x1, y1, w, h)
            else:
                self.crop_rect = None
        elif self.is_selecting and self.start_pos and self.current_pos:
            x1 = min(self.start_pos.x(), self.current_pos.x())
            y1 = min(self.start_pos.y(), self.current_pos.y())
            x2 = max(self.start_pos.x(), self.current_pos.x())
            y2 = max(self.start_pos.y(), self.current_pos.y())
            self.crop_rect = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))

        # 2. Draw clear (un-darkened) original image section inside crop box
        if self.crop_rect and self.crop_rect.width() > 0 and self.crop_rect.height() > 0:
            scale_x, scale_y = self._get_scale_factors()
            src_x = int(round(self.crop_rect.x() * scale_x))
            src_y = int(round(self.crop_rect.y() * scale_y))
            src_w = int(round(self.crop_rect.width() * scale_x))
            src_h = int(round(self.crop_rect.height() * scale_y))
            src_rect = QRect(src_x, src_y, src_w, src_h)

            painter.drawPixmap(self.crop_rect, self.original_pixmap, src_rect)

            # Draw Crop HUD grid, border, handles, and dimension tag
            self.draw_crop_hud(painter, self.crop_rect)

        # 3. Draw viewfinder crosshair only on the monitor under the cursor
        if cursor_here and (not self.crop_rect or self.is_selecting):
            self.draw_hud_reticle(painter, cx, cy)

        # 4. Draw Top HUD Status Banner with Cancel button
        self.draw_top_bar(painter)

    def draw_hud_reticle(self, painter, cx, cy):
        """Draws viewfinder crosshair lines and coordinate pill near cursor."""
        pen = QPen(self.hud_color, 1.2)
        painter.setPen(pen)

        painter.drawLine(cx - 15, cy, cx - 4, cy)
        painter.drawLine(cx + 4, cy, cx + 15, cy)
        painter.drawLine(cx, cy - 15, cx, cy - 4)
        painter.drawLine(cx, cy + 4, cx, cy + 15)

        coord_text = f"X:{cx:04d}\nY:{cy:04d}"
        font = QFont("Consolas", 8, QFont.Weight.Bold)
        painter.setFont(font)

        pill_rect = QRect(cx + 18, cy + 18, 56, 30)
        painter.setBrush(QBrush(self.hud_bg))
        painter.drawRoundedRect(pill_rect, 4, 4)
        painter.setPen(QPen(self.hud_color))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, coord_text)

    def draw_crop_hud(self, painter, rect):
        """Draws dashed cyan border, rule-of-thirds grid, handles, and confirm button."""
        x1, y1, w, h = rect.x(), rect.y(), rect.width(), rect.height()

        # Dashed border line
        border_pen = QPen(self.hud_color, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Rule of Thirds gridlines
        grid_pen = QPen(self.hud_color, 0.8, Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)

        dx = w / 3.0
        dy = h / 3.0
        painter.drawLine(int(round(x1 + dx)), y1, int(round(x1 + dx)), y1 + h)
        painter.drawLine(int(round(x1 + 2 * dx)), y1, int(round(x1 + 2 * dx)), y1 + h)
        painter.drawLine(x1, int(round(y1 + dy)), x1 + w, int(round(y1 + dy)))
        painter.drawLine(x1, int(round(y1 + 2 * dy)), x1 + w, int(round(y1 + 2 * dy)))

        # 8 Handle Grips
        handle_pen = QPen(self.hud_color, 1.2)
        handle_brush = QBrush(QColor("#FFFFFF"))
        painter.setPen(handle_pen)
        painter.setBrush(handle_brush)

        for h_rect in self.get_crop_handle_rects().values():
            painter.drawRect(h_rect)

        # Dimension pill tag
        dim_text = f"{w} x {h} px"
        font = QFont("Consolas", 9, QFont.Weight.Bold)
        painter.setFont(font)

        tag_w = 110
        tag_h = 22
        tag_x = int(round(x1 + (w - tag_w) / 2.0))
        tag_y = y1 - 26 if y1 > 30 else y1 + h + 6

        tag_rect = QRect(tag_x, tag_y, tag_w, tag_h)
        painter.setPen(QPen(self.hud_color, 1))
        painter.setBrush(QBrush(self.hud_bg))
        painter.drawRoundedRect(tag_rect, 4, 4)

        painter.setPen(QPen(self.hud_color))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, dim_text)

        # Floating Confirm Snip Button Pill
        if not self.is_selecting and self.mode != "fixed":
            confirm_w = 135
            confirm_h = 32
            confirm_x = x1 + w - confirm_w
            confirm_y = y1 + h + 8
            if confirm_y + confirm_h > self.height():
                confirm_y = y1 - confirm_h - 8

            self.confirm_btn_rect = QRect(confirm_x, confirm_y, confirm_w, confirm_h)
            mouse_pos = self.mapFromGlobal(QCursor.pos())
            is_hover = self.confirm_btn_rect.contains(mouse_pos)

            btn_bg = QColor("#005FB8") if is_hover else QColor("#007AFF")
            painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
            painter.setBrush(QBrush(btn_bg))
            painter.drawRoundedRect(self.confirm_btn_rect, 6, 6)

            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.setPen(QPen(QColor("#FFFFFF")))
            painter.drawText(self.confirm_btn_rect, Qt.AlignmentFlag.AlignCenter, "✓ CONFIRM (↵)")

    def draw_top_bar(self, painter):
        """Draws top HUD banner with instructions and a clickable Cancel button."""
        screen_w = self.width()
        cx = screen_w // 2
        cy = 28

        pill_w = 540
        pill_h = 38
        x1 = cx - pill_w // 2
        y1 = cy - pill_h // 2

        container_rect = QRect(x1, y1, pill_w, pill_h)
        painter.setPen(QPen(self.hud_color, 1.5))
        painter.setBrush(QBrush(QColor("#0E1013")))
        painter.drawRoundedRect(container_rect, 6, 6)

        # Instructions text
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor("#FFFFFF")))
        text_rect = QRect(x1 + 16, y1, 410, pill_h)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "📷 CAPTURE MODE  •  Drag box & adjust handles  •  Enter/Click Confirm")

        # Cancel button rect
        btn_w = 95
        btn_h = pill_h - 8
        btn_x = x1 + pill_w - btn_w - 6
        btn_y = y1 + 4
        self.cancel_btn_rect = QRect(btn_x, btn_y, btn_w, btn_h)

        mouse_pos = self.mapFromGlobal(QCursor.pos())
        is_hover = self.cancel_btn_rect.contains(mouse_pos)

        btn_bg = QColor("#B71C1C") if is_hover else QColor("#D32F2F")
        btn_border = QColor("#FFFFFF") if is_hover else QColor("#FF6B6B")

        painter.setPen(QPen(btn_border, 1))
        painter.setBrush(QBrush(btn_bg))
        painter.drawRoundedRect(self.cancel_btn_rect, 4, 4)

        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(self.cancel_btn_rect, Qt.AlignmentFlag.AlignCenter, "✕ CANCEL")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()

            if self.cancel_btn_rect and self.cancel_btn_rect.contains(pos):
                self.cancel()
                return

            if self.confirm_btn_rect and self.confirm_btn_rect.contains(pos):
                self.confirm_snip()
                return

            handle = self.handle_at(pos)
            if handle != self.HANDLE_NONE:
                self.active_handle = handle
                self.drag_start_pos = pos
                self.start_crop_rect = QRect(self.crop_rect)
                return

            if self.crop_rect and self.crop_rect.contains(pos) and self.mode != "fixed":
                self.active_handle = self.HANDLE_NONE
                self.drag_start_pos = pos
                self.start_crop_rect = QRect(self.crop_rect)
                return

            # A new selection on this monitor clears selections on the other monitors
            self.controller.clear_others(self)

            if self.mode == "fixed":
                w, h = self.fixed_width, self.fixed_height
                sw, sh = self.width(), self.height()
                x1 = max(0, min(pos.x() - w // 2, sw - w))
                y1 = max(0, min(pos.y() - h // 2, sh - h))
                self.crop_rect = QRect(x1, y1, w, h)
                self.confirm_snip()
            else:
                self.start_pos = pos
                self.current_pos = pos
                self.is_selecting = True
                self.crop_rect = None
                self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        self.controller.notify_hover(self)

        # Update cursor shape on buttons or handles
        if self.cancel_btn_rect and self.cancel_btn_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self.confirm_btn_rect and self.confirm_btn_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            h = self.handle_at(pos)
            if h in (self.HANDLE_NW, self.HANDLE_SE):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h in (self.HANDLE_NE, self.HANDLE_SW):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif h in (self.HANDLE_N, self.HANDLE_S):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif h in (self.HANDLE_E, self.HANDLE_W):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self.crop_rect and self.crop_rect.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.BlankCursor)

        if self.drag_start_pos and self.start_crop_rect:
            dx = pos.x() - self.drag_start_pos.x()
            dy = pos.y() - self.drag_start_pos.y()
            r = self.start_crop_rect

            if self.active_handle == self.HANDLE_NONE:
                x1 = max(0, min(r.x() + dx, self.width() - r.width()))
                y1 = max(0, min(r.y() + dy, self.height() - r.height()))
                self.crop_rect = QRect(x1, y1, r.width(), r.height())

            elif self.active_handle == self.HANDLE_SE:
                self.crop_rect = QRect(r.x(), r.y(), max(10, r.width() + dx), max(10, r.height() + dy))
            elif self.active_handle == self.HANDLE_NW:
                x1 = min(r.x() + dx, r.x() + r.width() - 10)
                y1 = min(r.y() + dy, r.y() + r.height() - 10)
                self.crop_rect = QRect(x1, y1, r.x() + r.width() - x1, r.y() + r.height() - y1)
            elif self.active_handle in (self.HANDLE_E, self.HANDLE_NE):
                self.crop_rect = QRect(r.x(), r.y(), max(10, r.width() + dx), r.height())
            elif self.active_handle in (self.HANDLE_W, self.HANDLE_SW):
                x1 = min(r.x() + dx, r.x() + r.width() - 10)
                self.crop_rect = QRect(x1, r.y(), r.x() + r.width() - x1, r.height())
            elif self.active_handle == self.HANDLE_S:
                self.crop_rect = QRect(r.x(), r.y(), r.width(), max(10, r.height() + dy))
            elif self.active_handle == self.HANDLE_N:
                y1 = min(r.y() + dy, r.y() + r.height() - 10)
                self.crop_rect = QRect(r.x(), y1, r.width(), r.y() + r.height() - y1)

            # Keep the box inside this monitor
            if self.crop_rect:
                self.crop_rect = self.crop_rect.intersected(self.rect())

        elif self.is_selecting:
            # Selection is limited to the monitor where it started
            self.current_pos = self._clamp_to_widget(pos)

        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_selecting:
                self.is_selecting = False
                if self.start_pos and self.original_image:
                    self.current_pos = self._clamp_to_widget(event.position().toPoint())
                    x1 = min(self.start_pos.x(), self.current_pos.x())
                    y1 = min(self.start_pos.y(), self.current_pos.y())
                    x2 = max(self.start_pos.x(), self.current_pos.x())
                    y2 = max(self.start_pos.y(), self.current_pos.y())
                    self.crop_rect = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
                    self.confirm_snip()
                    return

            self.active_handle = self.HANDLE_NONE
            self.drag_start_pos = None
            self.start_crop_rect = None
            self.update()

    def crop_selection(self):
        """Returns a PIL crop of the current selection on this monitor, or None."""
        if not (self.crop_rect and self.original_image):
            return None
        scale_x, scale_y = self._get_scale_factors()
        ix1 = max(0, int(round(self.crop_rect.x() * scale_x)))
        iy1 = max(0, int(round(self.crop_rect.y() * scale_y)))
        ix2 = min(self.original_image.width, int(round((self.crop_rect.x() + self.crop_rect.width()) * scale_x)))
        iy2 = min(self.original_image.height, int(round((self.crop_rect.y() + self.crop_rect.height()) * scale_y)))
        if (ix2 - ix1) > 2 and (iy2 - iy1) > 2:
            return self.original_image.crop((ix1, iy1, ix2, iy2))
        return None

    def confirm_snip(self):
        self.controller.finish(self.crop_selection())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.controller.confirm_any()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel()

    def cancel(self):
        self.controller.finish(None)


class CaptureOverlay:
    """
    Snip controller. Opens one overlay per connected monitor; each overlay shows
    only that monitor's content at its native resolution, so you select on the
    actual screen you're looking at. Public API is unchanged:
        CaptureOverlay(main_window, mode=..., fixed_width=..., fixed_height=..., callback=...)
    """

    def __init__(self, main_window, mode="free", fixed_width=800, fixed_height=600, callback=None):
        self.main_window = main_window
        self.mode = mode
        self.callback = callback
        self.captured_image = None
        self.overlays = []
        self._hover_overlay = None
        self._finished = False

        # Hide main window completely and set opacity to 0.0 to prevent shadow artifacts
        if self.main_window:
            self.main_window.setWindowOpacity(0.0)
            self.main_window.hide()
        for _ in range(6):
            QApplication.processEvents()
            time.sleep(0.06)

        screens = [s for s in QApplication.screens() if s is not None] or [QApplication.primaryScreen()]
        shots = self.take_screenshots(screens)

        for screen, img in zip(screens, shots):
            ov = _ScreenOverlay(self, screen, img, mode=mode,
                                fixed_width=fixed_width, fixed_height=fixed_height)
            self.overlays.append(ov)

        # Focus the overlay on the monitor where the cursor currently is
        start = self._overlay_under_cursor() or (self.overlays[0] if self.overlays else None)
        if start:
            start.activateWindow()
            start.raise_()
            start.setFocus()
            self._hover_overlay = start

    # ---------- screenshots ----------
    @staticmethod
    def _native_rect(screen):
        """Physical-pixel rect of a screen (Qt keeps the native top-left; size is DPI-scaled)."""
        g = screen.geometry()
        dpr = screen.devicePixelRatio()
        return g.x(), g.y(), int(round(g.width() * dpr)), int(round(g.height() * dpr))

    def take_screenshots(self, screens):
        """Returns one PIL image per screen containing only that screen's pixels."""
        results = [None] * len(screens)

        # 1) Qt per-screen grab (handles mixed DPI and negative monitor coordinates)
        for i, screen in enumerate(screens):
            try:
                pm = screen.grabWindow(0)
                if pm and not pm.isNull() and pm.width() > 1 and pm.height() > 1:
                    results[i] = qimage_to_pil(pm.toImage())
            except Exception:
                results[i] = None

        # 2) Fallback: PIL grab of the whole virtual desktop, cropped per monitor
        if any(r is None for r in results):
            full = None
            try:
                full = ImageGrab.grab(all_screens=True)
            except Exception:
                try:
                    full = ImageGrab.grab()
                except Exception:
                    full = None

            if full:
                rects = [self._native_rect(s) for s in screens]
                vx = min(r[0] for r in rects)
                vy = min(r[1] for r in rects)
                for i, (x, y, w, h) in enumerate(rects):
                    if results[i] is None:
                        left, top = max(0, x - vx), max(0, y - vy)
                        right = min(full.width, left + w)
                        bottom = min(full.height, top + h)
                        if right - left > 1 and bottom - top > 1:
                            results[i] = full.crop((left, top, right, bottom))

        # 3) Last resort: blank white image
        for i, r in enumerate(results):
            if r is None:
                g = screens[i].geometry()
                results[i] = Image.new("RGBA", (max(1, g.width()), max(1, g.height())), (255, 255, 255, 255))
        return results

    # ---------- coordination between monitors ----------
    def _overlay_under_cursor(self):
        for ov in self.overlays:
            if ov.cursor_on_this_screen():
                return ov
        return None

    def notify_hover(self, overlay):
        """Repaint the monitor the cursor just left so its reticle / fixed box disappears."""
        if self._hover_overlay is not overlay:
            prev = self._hover_overlay
            self._hover_overlay = overlay
            if prev is not None and prev in self.overlays:
                prev.update()

    def clear_others(self, keep):
        for ov in self.overlays:
            if ov is not keep:
                ov.clear_selection()

    def confirm_any(self):
        for ov in self.overlays:
            if ov.crop_rect:
                self.finish(ov.crop_selection())
                return
        self.finish(None)

    def finish(self, image):
        if self._finished:
            return
        self._finished = True
        self.captured_image = image

        overlays, self.overlays = self.overlays, []
        for ov in overlays:
            try:
                ov.releaseMouse()
            except Exception:
                pass
            ov.close()

        if self.main_window:
            self.main_window.setWindowOpacity(1.0)
            self.main_window.show()
            self.main_window.activateWindow()
            self.main_window.raise_()

        if self.callback:
            self.callback(self.captured_image)

    # Backwards-compatible aliases
    def cancel(self):
        self.finish(None)

    def close_overlay(self):
        self.finish(self.captured_image)
