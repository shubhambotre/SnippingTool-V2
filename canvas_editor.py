import math
import os
import copy
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QObject, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPixmap, QImage,
    QPainterPath, QTransform, QKeySequence, QFontMetrics
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsPathItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsLineItem, QGraphicsItemGroup, QGraphicsItem
)

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


def make_arrow_path(start, end, head_len=14, angle_deg=25):
    """Generates a QPainterPath for a vector arrow with arrowhead polygon."""
    path = QPainterPath()
    path.moveTo(start)
    path.lineTo(end)

    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length = math.hypot(dx, dy)
    if length > 2:
        angle = math.atan2(dy, dx)
        rad1 = angle + math.radians(180 - angle_deg)
        rad2 = angle - math.radians(180 - angle_deg)

        p1 = QPointF(end.x() + head_len * math.cos(rad1), end.y() + head_len * math.sin(rad1))
        p2 = QPointF(end.x() + head_len * math.cos(rad2), end.y() + head_len * math.sin(rad2))

        arrow_head = QPainterPath()
        arrow_head.moveTo(end)
        arrow_head.lineTo(p1)
        arrow_head.lineTo(p2)
        arrow_head.closeSubpath()
        path.addPath(arrow_head)

    return path


class SelectionBoxOverlayItem(QGraphicsItem):
    """Overlay item that renders an 8-point interactive resize/transform box around selected QGraphicsItems."""
    
    HANDLE_NONE = 0
    HANDLE_NW = 1
    HANDLE_N = 2
    HANDLE_NE = 3
    HANDLE_E = 4
    HANDLE_SE = 5
    HANDLE_S = 6
    HANDLE_SW = 7
    HANDLE_W = 8
    
    HANDLE_SIZE = 9.0

    def __init__(self, canvas_editor):
        super().__init__()
        self.canvas_editor = canvas_editor
        self.target_item = None
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        self.start_scale = 1.0
        self.start_rect = QRectF()
        self.start_scene_rect = QRectF()
        self.setZValue(1000)
        self.setAcceptHoverEvents(True)
        self.hide()

    def update_target(self):
        if not self.canvas_editor or not self.canvas_editor.scene:
            return
        selected = []
        try:
            selected = [
                i for i in self.canvas_editor.scene.selectedItems()
                if i != self and i != self.canvas_editor.bg_pixmap_item and i != self.canvas_editor.crop_item
            ]
        except RuntimeError:
            self.target_item = None
            self.hide()
            return

        if selected:
            self.target_item = selected[0]
            try:
                rect = self.target_item.sceneBoundingRect()
                self.setPos(rect.topLeft())
                self.start_rect = QRectF(0, 0, rect.width(), rect.height())
                self.prepareGeometryChange()
                self.show()
                self.update()
            except RuntimeError:
                self.target_item = None
                self.hide()
        else:
            self.target_item = None
            self.hide()

    def boundingRect(self):
        hs = self.HANDLE_SIZE
        r = self.start_rect
        return QRectF(-hs, -hs, r.width() + 2 * hs, r.height() + 2 * hs)

    def get_handle_rects(self):
        r = self.start_rect
        hs = self.HANDLE_SIZE
        h_half = hs / 2.0

        x0, y0 = 0, 0
        x1, y1 = r.width() / 2.0, r.height() / 2.0
        x2, y2 = r.width(), r.height()

        return {
            self.HANDLE_NW: QRectF(x0 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_N:  QRectF(x1 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_NE: QRectF(x2 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_E:  QRectF(x2 - h_half, y1 - h_half, hs, hs),
            self.HANDLE_SE: QRectF(x2 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_S:  QRectF(x1 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_SW: QRectF(x0 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_W:  QRectF(x0 - h_half, y1 - h_half, hs, hs),
        }

    def paint(self, painter, option, widget=None):
        if not self.target_item:
            return

        r = self.start_rect
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dashed bounding rectangle outline
        pen = QPen(QColor("#00E5FF"), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        # 8 Handle square grips
        handle_pen = QPen(QColor("#00E5FF"), 1.2)
        handle_brush = QBrush(QColor("#FFFFFF"))
        painter.setPen(handle_pen)
        painter.setBrush(handle_brush)

        for rect in self.get_handle_rects().values():
            painter.drawRect(rect)

    def handle_at(self, pos):
        for handle, rect in self.get_handle_rects().items():
            if rect.contains(pos):
                return handle
        return self.HANDLE_NONE

    def hoverMoveEvent(self, event):
        h = self.handle_at(event.pos())
        if h in (self.HANDLE_NW, self.HANDLE_SE):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif h in (self.HANDLE_NE, self.HANDLE_SW):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif h in (self.HANDLE_N, self.HANDLE_S):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif h in (self.HANDLE_E, self.HANDLE_W):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.active_handle = self.handle_at(event.pos())
            self.drag_start_pos = event.scenePos()
            if self.target_item:
                try:
                    self.start_scale = self.target_item.scale()
                    self.start_item_pos = self.target_item.pos()
                    self.start_scene_rect = self.target_item.sceneBoundingRect()
                except RuntimeError:
                    self.target_item = None
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.target_item and self.drag_start_pos:
            curr_pos = event.scenePos()
            dx = curr_pos.x() - self.drag_start_pos.x()
            dy = curr_pos.y() - self.drag_start_pos.y()

            try:
                if self.active_handle == self.HANDLE_NONE:
                    self.target_item.setPos(self.start_item_pos.x() + dx, self.start_item_pos.y() + dy)
                    self.update_target()
                    event.accept()
                    return

                r = self.start_scene_rect
                new_l, new_t, new_r, new_b = r.left(), r.top(), r.right(), r.bottom()

                if self.active_handle == self.HANDLE_SE:
                    new_r = max(r.left() + 10, r.right() + dx)
                    new_b = max(r.top() + 10, r.bottom() + dy)
                elif self.active_handle == self.HANDLE_NW:
                    new_l = min(r.right() - 10, r.left() + dx)
                    new_t = min(r.bottom() - 10, r.top() + dy)
                elif self.active_handle == self.HANDLE_NE:
                    new_t = min(r.bottom() - 10, r.top() + dy)
                    new_r = max(r.left() + 10, r.right() + dx)
                elif self.active_handle == self.HANDLE_SW:
                    new_l = min(r.right() - 10, r.left() + dx)
                    new_b = max(r.top() + 10, r.bottom() + dy)
                elif self.active_handle == self.HANDLE_E:
                    new_r = max(r.left() + 10, r.right() + dx)
                elif self.active_handle == self.HANDLE_W:
                    new_l = min(r.right() - 10, r.left() + dx)
                elif self.active_handle == self.HANDLE_S:
                    new_b = max(r.top() + 10, r.bottom() + dy)
                elif self.active_handle == self.HANDLE_N:
                    new_t = min(r.bottom() - 10, r.top() + dy)

                new_w = max(5.0, new_r - new_l)
                new_h = max(5.0, new_b - new_t)

                if isinstance(self.target_item, (QGraphicsRectItem, QGraphicsEllipseItem)):
                    self.target_item.setPos(new_l, new_t)
                    self.target_item.setRect(0, 0, new_w, new_h)
                    self.target_item.setScale(1.0)
                else:
                    sw = max(5.0, r.width())
                    sh = max(5.0, r.height())
                    scale_factor = max(0.05, max(new_w / sw, new_h / sh))
                    self.target_item.setPos(new_l, new_t)
                    self.target_item.setScale(self.start_scale * scale_factor)

                self.update_target()
            except RuntimeError:
                self.target_item = None
                self.hide()

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        super().mouseReleaseEvent(event)


class CanvasCropOverlayItem(QGraphicsItem):
    """Interactive canvas crop box with 8 handles and floating '✓ Apply Crop' pill button."""

    HANDLE_NONE = 0
    HANDLE_NW = 1
    HANDLE_N = 2
    HANDLE_NE = 3
    HANDLE_E = 4
    HANDLE_SE = 5
    HANDLE_S = 6
    HANDLE_SW = 7
    HANDLE_W = 8

    HANDLE_SIZE = 9.0

    def __init__(self, canvas_editor, rect):
        super().__init__()
        self.canvas_editor = canvas_editor
        self.crop_rect = QRectF(rect).normalized()
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        self.start_crop_rect = QRectF()
        self.setZValue(2000)
        self.setAcceptHoverEvents(True)
        self.confirm_btn_rect = QRectF()
        self.cancel_btn_rect = QRectF()

    def boundingRect(self):
        r = self.crop_rect
        hs = self.HANDLE_SIZE + 40
        return QRectF(r.x() - hs, r.y() - hs, r.width() + 2 * hs, r.height() + 2 * hs + 60)

    def get_handle_rects(self):
        r = self.crop_rect
        hs = self.HANDLE_SIZE
        h_half = hs / 2.0

        x0, y0 = r.x(), r.y()
        x1, y1 = r.x() + r.width() / 2.0, r.y() + r.height() / 2.0
        x2, y2 = r.x() + r.width(), r.y() + r.height()

        return {
            self.HANDLE_NW: QRectF(x0 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_N:  QRectF(x1 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_NE: QRectF(x2 - h_half, y0 - h_half, hs, hs),
            self.HANDLE_E:  QRectF(x2 - h_half, y1 - h_half, hs, hs),
            self.HANDLE_SE: QRectF(x2 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_S:  QRectF(x1 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_SW: QRectF(x0 - h_half, y2 - h_half, hs, hs),
            self.HANDLE_W:  QRectF(x0 - h_half, y1 - h_half, hs, hs),
        }

    def handle_at(self, pos):
        for handle, rect in self.get_handle_rects().items():
            if rect.contains(pos):
                return handle
        return self.HANDLE_NONE

    def paint(self, painter, option, widget=None):
        r = self.crop_rect
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dashed cyan crop border
        border_pen = QPen(QColor("#00E5FF"), 1.8, Qt.PenStyle.DashLine)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        # 8 Handle square grips
        handle_pen = QPen(QColor("#00E5FF"), 1.2)
        handle_brush = QBrush(QColor("#FFFFFF"))
        painter.setPen(handle_pen)
        painter.setBrush(handle_brush)
        for h_rect in self.get_handle_rects().values():
            painter.drawRect(h_rect)

        # Floating Confirm and Cancel Pill Buttons below crop box
        btn_w, btn_h = 115.0, 30.0
        btn_y = r.bottom() + 10
        btn_x_confirm = r.right() - btn_w
        btn_x_cancel = btn_x_confirm - 95.0

        self.confirm_btn_rect = QRectF(btn_x_confirm, btn_y, btn_w, btn_h)
        self.cancel_btn_rect = QRectF(btn_x_cancel, btn_y, 85.0, btn_h)

        # Confirm Button (Cobalt Blue)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        painter.setBrush(QBrush(QColor("#005FB8")))
        painter.drawRoundedRect(self.confirm_btn_rect, 6, 6)

        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(self.confirm_btn_rect, Qt.AlignmentFlag.AlignCenter, "✓ APPLY CROP")

        # Cancel Button (Red)
        painter.setPen(QPen(QColor("#FFFFFF"), 1.2))
        painter.setBrush(QBrush(QColor("#D32F2F")))
        painter.drawRoundedRect(self.cancel_btn_rect, 6, 6)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(self.cancel_btn_rect, Qt.AlignmentFlag.AlignCenter, "✕ CANCEL")

    def hoverMoveEvent(self, event):
        pos = event.pos()
        if self.confirm_btn_rect.contains(pos) or self.cancel_btn_rect.contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return

        h = self.handle_at(pos)
        if h in (self.HANDLE_NW, self.HANDLE_SE):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif h in (self.HANDLE_NE, self.HANDLE_SW):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif h in (self.HANDLE_N, self.HANDLE_S):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif h in (self.HANDLE_E, self.HANDLE_W):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self.crop_rect.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self.confirm_btn_rect.contains(pos):
                event.accept()
                QTimer.singleShot(0, self.apply_crop)
                return
            if self.cancel_btn_rect.contains(pos):
                event.accept()
                QTimer.singleShot(0, self.cancel_crop)
                return

            self.active_handle = self.handle_at(pos)
            self.drag_start_pos = event.scenePos()
            self.start_crop_rect = QRectF(self.crop_rect)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start_pos:
            curr = event.scenePos()
            dx = curr.x() - self.drag_start_pos.x()
            dy = curr.y() - self.drag_start_pos.y()
            r = self.start_crop_rect

            self.prepareGeometryChange()
            if self.active_handle == self.HANDLE_NONE:
                self.crop_rect = QRectF(r.x() + dx, r.y() + dy, r.width(), r.height())
            elif self.active_handle == self.HANDLE_SE:
                self.crop_rect = QRectF(r.x(), r.y(), max(10, r.width() + dx), max(10, r.height() + dy))
            elif self.active_handle == self.HANDLE_NW:
                x1 = min(r.x() + dx, r.right() - 10)
                y1 = min(r.y() + dy, r.bottom() - 10)
                self.crop_rect = QRectF(x1, y1, r.right() - x1, r.bottom() - y1)
            elif self.active_handle == self.HANDLE_NE:
                y1 = min(r.y() + dy, r.bottom() - 10)
                self.crop_rect = QRectF(r.x(), y1, max(10, r.width() + dx), r.bottom() - y1)
            elif self.active_handle == self.HANDLE_SW:
                x1 = min(r.x() + dx, r.right() - 10)
                self.crop_rect = QRectF(x1, r.y(), r.right() - x1, max(10, r.height() + dy))
            elif self.active_handle == self.HANDLE_E:
                self.crop_rect = QRectF(r.x(), r.y(), max(10, r.width() + dx), r.height())
            elif self.active_handle == self.HANDLE_W:
                x1 = min(r.x() + dx, r.right() - 10)
                self.crop_rect = QRectF(x1, r.y(), r.right() - x1, r.height())
            elif self.active_handle == self.HANDLE_S:
                self.crop_rect = QRectF(r.x(), r.y(), r.width(), max(10, r.height() + dy))
            elif self.active_handle == self.HANDLE_N:
                y1 = min(r.y() + dy, r.bottom() - 10)
                self.crop_rect = QRectF(r.x(), y1, r.width(), r.bottom() - y1)

            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.active_handle = self.HANDLE_NONE
        self.drag_start_pos = None
        super().mouseReleaseEvent(event)

    def apply_crop(self):
        crop_r = self.crop_rect.toRect()
        if crop_r.width() > 5 and crop_r.height() > 5 and self.canvas_editor:
            self.canvas_editor.apply_crop(crop_r)
        self.cancel_crop()

    def cancel_crop(self):
        if self.canvas_editor:
            if getattr(self.canvas_editor, 'crop_overlay_item', None) == self:
                self.canvas_editor.crop_overlay_item = None
            if self.canvas_editor.scene:
                try:
                    self.canvas_editor.scene.removeItem(self)
                except (RuntimeError, Exception):
                    pass
            self.canvas_editor.set_tool("select")
            if self.canvas_editor.on_tool_change_callback:
                self.canvas_editor.on_tool_change_callback("select")


class CanvasEditor(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform |
            QPainter.RenderHint.TextAntialiasing
        )

        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Image containers
        self.base_image = None
        self.bg_pixmap_item = None

        # State
        self.tool = "pencil"
        self.color = "#FF3B30"
        self.thickness = 3
        self.fill_mode = "hollow"
        self.font_size = 14
        self.font_family = "Arial"
        self.zoom_factor = 1.0

        # Drawing state
        self.start_point = None
        self.current_item = None
        self.pencil_path = None

        # Crop overlay state
        self.crop_item = None
        self.crop_overlay_item = None

        # Transform Handles Overlay
        self.selection_box = SelectionBoxOverlayItem(self)
        self.scene.addItem(self.selection_box)
        self.scene.selectionChanged.connect(self.selection_box.update_target)

        # Element history stack for Undo/Redo
        self.history = []
        self.redo_stack = []

        # Callbacks
        self.on_draw_callback = None
        self.cursor_callback = None
        self.on_crop_complete_callback = None
        self.on_tool_change_callback = None

        # Dark grid background
        self.setBackgroundBrush(QBrush(QColor("#1E1E1E")))
        self.set_tool("pencil")

    def set_image(self, pil_image):
        """Loads a PIL image into the canvas scene."""
        self.base_image = pil_image.copy()
        self.current_item = None
        self.crop_item = None
        self.crop_overlay_item = None
        self.scene.clear()
        
        # Re-add selection box
        self.selection_box = SelectionBoxOverlayItem(self)
        self.scene.addItem(self.selection_box)
        self.scene.selectionChanged.connect(self.selection_box.update_target)

        self.history.clear()
        self.redo_stack.clear()
        self.zoom_factor = 1.0
        self.resetTransform()

        pixmap = pil_to_qpixmap(self.base_image)
        self.bg_pixmap_item = self.scene.addPixmap(pixmap)
        self.bg_pixmap_item.setZValue(-100)

        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        if self.on_crop_complete_callback:
            self.on_crop_complete_callback(pixmap.width(), pixmap.height())

    def set_tool(self, tool_name):
        if self.tool == tool_name:
            return
        self.tool = tool_name
        self.set_interactive_mode()

        if tool_name in ("pencil", "highlighter", "line", "arrow", "rectangle", "circle", "crop"):
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif tool_name == "text":
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif tool_name == "eraser":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_color(self, color_hex):
        self.color = color_hex
        self.update_selected_item_style()

    def set_thickness(self, thickness):
        self.thickness = thickness
        self.update_selected_item_style()

    def set_fill_mode(self, mode):
        self.fill_mode = mode
        self.update_selected_item_style()

    def set_font_size(self, size):
        self.font_size = size
        self.update_selected_item_style()

    def set_font_family(self, family):
        self.font_family = family
        self.update_selected_item_style()

    def set_interactive_mode(self):
        """Configures item selection and drag flags based on current tool."""
        is_select = (self.tool == "select")
        for item in self.scene.items():
            if item != self.bg_pixmap_item and item != self.crop_item and item != self.selection_box and item != getattr(self, 'crop_overlay_item', None):
                try:
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, is_select)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, is_select)
                except RuntimeError:
                    pass
        
        if not is_select:
            self.scene.clearSelection()

    def update_selected_item_style(self):
        """Applies tool styling (color, stroke, font) to currently selected items."""
        if self.tool != "select":
            return

        for item in self.scene.selectedItems():
            if item == self.selection_box or item == self.bg_pixmap_item:
                continue
            pen_color = QColor(self.color)
            pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

            try:
                if isinstance(item, QGraphicsPathItem):
                    item.setPen(pen)
                elif isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
                    item.setPen(pen)
                    if self.fill_mode == "filled":
                        item.setBrush(QBrush(pen_color))
                    else:
                        item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                elif isinstance(item, QGraphicsTextItem):
                    item.setDefaultTextColor(pen_color)
                    font = QFont(self.font_family, self.font_size)
                    font.setBold(True)
                    item.setFont(font)
            except RuntimeError:
                pass
        
        self.selection_box.update_target()

    def mousePressEvent(self, event):
        if not self.bg_pixmap_item:
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())

        # Clean up any un-edited empty text items before processing mouse press
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsTextItem) and item != self.scene.focusItem():
                if not item.toPlainText().strip():
                    if item in self.history:
                        self.history.remove(item)
                    try:
                        self.scene.removeItem(item)
                    except RuntimeError:
                        pass

        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool == "select":
                super().mousePressEvent(event)
                return

            self.start_point = scene_pos
            pen_color = QColor(self.color)

            if self.tool == "highlighter":
                pen_color.setAlpha(100)
                pen = QPen(pen_color, 18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                self.pencil_path = QPainterPath(scene_pos)
                self.current_item = self.scene.addPath(self.pencil_path, pen)

            elif self.tool == "pencil":
                pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                self.pencil_path = QPainterPath(scene_pos)
                self.current_item = self.scene.addPath(self.pencil_path, pen)

            elif self.tool == "line":
                pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                self.current_item = self.scene.addLine(scene_pos.x(), scene_pos.y(), scene_pos.x(), scene_pos.y(), pen)

            elif self.tool == "arrow":
                pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                path = make_arrow_path(scene_pos, scene_pos, head_len=max(10, self.thickness * 3.5))
                fill_brush = QBrush(pen_color)
                self.current_item = self.scene.addPath(path, pen, fill_brush)

            elif self.tool == "rectangle":
                pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
                fill_brush = QBrush(pen_color) if self.fill_mode == "filled" else QBrush(Qt.BrushStyle.NoBrush)
                self.current_item = self.scene.addRect(QRectF(scene_pos, scene_pos), pen, fill_brush)

            elif self.tool == "circle":
                pen = QPen(pen_color, self.thickness, Qt.PenStyle.SolidLine)
                fill_brush = QBrush(pen_color) if self.fill_mode == "filled" else QBrush(Qt.BrushStyle.NoBrush)
                self.current_item = self.scene.addEllipse(QRectF(scene_pos, scene_pos), pen, fill_brush)

            elif self.tool == "text":
                text_item = QGraphicsTextItem("")
                font = QFont(self.font_family, self.font_size)
                font.setBold(True)
                text_item.setFont(font)
                text_item.setDefaultTextColor(pen_color)
                text_item.setPos(scene_pos)
                text_item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
                text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                self.scene.addItem(text_item)
                self.history.append(text_item)
                self.redo_stack.clear()

                self.set_tool("select")
                if self.on_tool_change_callback:
                    self.on_tool_change_callback("select")
                self.scene.clearSelection()
                text_item.setSelected(True)
                text_item.setFocus()

                if self.on_draw_callback:
                    self.on_draw_callback()

            elif self.tool == "eraser":
                item_at_pos = self.scene.itemAt(scene_pos, QTransform())
                if item_at_pos and item_at_pos != self.bg_pixmap_item and item_at_pos != self.selection_box:
                    try:
                        self.scene.removeItem(item_at_pos)
                        if item_at_pos in self.history:
                            self.history.remove(item_at_pos)
                    except RuntimeError:
                        pass

            elif self.tool == "crop":
                pen = QPen(QColor("#00E5FF"), 1.5, Qt.PenStyle.DashLine)
                self.current_item = self.scene.addRect(QRectF(scene_pos, scene_pos), pen)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.position().toPoint())

        if self.cursor_callback:
            self.cursor_callback(int(scene_pos.x()), int(scene_pos.y()))

        if self.tool == "eraser" and (event.buttons() & Qt.MouseButton.LeftButton):
            item_at_pos = self.scene.itemAt(scene_pos, QTransform())
            if item_at_pos and item_at_pos != self.bg_pixmap_item and item_at_pos != self.selection_box:
                try:
                    self.scene.removeItem(item_at_pos)
                    if item_at_pos in self.history:
                        self.history.remove(item_at_pos)
                except RuntimeError:
                    pass

        if self.start_point and self.current_item:
            try:
                if self.tool in ("pencil", "highlighter"):
                    self.pencil_path.lineTo(scene_pos)
                    self.current_item.setPath(self.pencil_path)

                elif self.tool == "line":
                    self.current_item.setLine(self.start_point.x(), self.start_point.y(), scene_pos.x(), scene_pos.y())

                elif self.tool == "arrow":
                    path = make_arrow_path(self.start_point, scene_pos, head_len=max(10, self.thickness * 3.5))
                    self.current_item.setPath(path)

                elif self.tool == "rectangle":
                    rect = QRectF(self.start_point, scene_pos).normalized()
                    self.current_item.setRect(rect)

                elif self.tool == "circle":
                    rect = QRectF(self.start_point, scene_pos).normalized()
                    self.current_item.setRect(rect)

                elif self.tool == "crop":
                    rect = QRectF(self.start_point, scene_pos).normalized()
                    self.current_item.setRect(rect)
            except RuntimeError:
                self.current_item = None
                self.start_point = None

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start_point:
            if self.tool == "crop" and self.current_item:
                crop_rect = QRectF()
                try:
                    crop_rect = self.current_item.rect()
                    self.scene.removeItem(self.current_item)
                except RuntimeError:
                    pass
                self.current_item = None
                self.start_point = None

                if crop_rect.width() > 10 and crop_rect.height() > 10:
                    if getattr(self, 'crop_overlay_item', None):
                        try:
                            self.scene.removeItem(self.crop_overlay_item)
                        except RuntimeError:
                            pass
                    self.crop_overlay_item = CanvasCropOverlayItem(self, crop_rect)
                    self.scene.addItem(self.crop_overlay_item)
            else:
                if self.current_item:
                    drawn_tool = self.tool
                    is_shape = drawn_tool in ("rectangle", "circle", "line", "arrow", "pencil", "highlighter")

                    if is_shape:
                        self.set_tool("select")
                        if self.on_tool_change_callback:
                            self.on_tool_change_callback("select")

                    try:
                        self.current_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                        self.current_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

                        if is_shape:
                            self.scene.clearSelection()
                            self.current_item.setSelected(True)

                        self.history.append(self.current_item)
                        self.redo_stack.clear()
                    except RuntimeError:
                        pass
                    if self.on_draw_callback:
                        self.on_draw_callback()
                self.current_item = None
                self.start_point = None

        super().mouseReleaseEvent(event)

    def apply_crop(self, crop_rect):
        """Crops the base image and bakes annotations."""
        if not self.base_image:
            return

        baked = self.get_baked_image()
        x1 = max(0, crop_rect.x())
        y1 = max(0, crop_rect.y())
        x2 = min(baked.width, crop_rect.x() + crop_rect.width())
        y2 = min(baked.height, crop_rect.y() + crop_rect.height())

        if x2 - x1 > 5 and y2 - y1 > 5:
            cropped = baked.crop((x1, y1, x2, y2))
            self.set_image(cropped)

    def wheelEvent(self, event):
        """Handles canvas zoom with Ctrl+Wheel or element scaling in Select mode."""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.15 if angle > 0 else 0.85
            new_zoom = self.zoom_factor * factor
            if 0.25 <= new_zoom <= 3.0:
                self.zoom_factor = new_zoom
                self.scale(factor, factor)
        elif self.tool == "select" and self.scene.selectedItems():
            angle = event.angleDelta().y()
            scale_delta = 1.1 if angle > 0 else 0.9
            for item in self.scene.selectedItems():
                if item != self.selection_box and item != self.bg_pixmap_item:
                    try:
                        item.setScale(item.scale() * scale_delta)
                    except RuntimeError:
                        pass
            self.selection_box.update_target()

    def keyPressEvent(self, event):
        """Handles keyboard shortcuts (Delete, Backspace, Enter/Return crop confirm, Ctrl+A, Nudging, +/- Scaling)."""
        focus_item = self.scene.focusItem()
        if isinstance(focus_item, QGraphicsTextItem) and (focus_item.textInteractionFlags() & Qt.TextInteractionFlag.TextEditorInteraction):
            super().keyPressEvent(event)
            return

        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and getattr(self, 'crop_overlay_item', None):
            try:
                self.crop_overlay_item.apply_crop()
            except RuntimeError:
                self.crop_overlay_item = None
            return
        elif event.key() == Qt.Key.Key_Escape and getattr(self, 'crop_overlay_item', None):
            try:
                self.crop_overlay_item.cancel_crop()
            except RuntimeError:
                self.crop_overlay_item = None
            return

        selected = [
            i for i in self.scene.selectedItems()
            if i != self.selection_box and i != self.bg_pixmap_item and i != self.crop_item
        ]

        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if selected:
                for item in selected:
                    if item in self.history:
                        self.history.remove(item)
                    try:
                        self.scene.removeItem(item)
                    except RuntimeError:
                        pass
                self.selection_box.update_target()
                if self.on_draw_callback:
                    self.on_draw_callback()
                return

        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_A:
            if self.tool == "select":
                for item in self.scene.items():
                    if item != self.bg_pixmap_item and item != self.crop_item and item != self.selection_box and item != getattr(self, 'crop_overlay_item', None):
                        try:
                            item.setSelected(True)
                        except RuntimeError:
                            pass
                return

        if not selected:
            super().keyPressEvent(event)
            return

        step = 5 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1

        if event.key() == Qt.Key.Key_Left:
            for item in selected:
                try:
                    item.moveBy(-step, 0)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        elif event.key() == Qt.Key.Key_Right:
            for item in selected:
                try:
                    item.moveBy(step, 0)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        elif event.key() == Qt.Key.Key_Up:
            for item in selected:
                try:
                    item.moveBy(0, -step)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        elif event.key() == Qt.Key.Key_Down:
            for item in selected:
                try:
                    item.moveBy(0, step)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        elif event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            for item in selected:
                try:
                    item.setScale(item.scale() * 1.1)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        elif event.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            for item in selected:
                try:
                    item.setScale(item.scale() * 0.9)
                except RuntimeError:
                    pass
            self.selection_box.update_target()
        else:
            super().keyPressEvent(event)

    def undo(self):
        if self.history:
            last_item = self.history.pop()
            try:
                self.scene.removeItem(last_item)
            except RuntimeError:
                pass
            self.redo_stack.append(last_item)
            self.selection_box.update_target()
            if self.on_draw_callback:
                self.on_draw_callback()

    def redo(self):
        if self.redo_stack:
            item = self.redo_stack.pop()
            try:
                self.scene.addItem(item)
            except RuntimeError:
                pass
            self.history.append(item)
            self.selection_box.update_target()
            if self.on_draw_callback:
                self.on_draw_callback()

    def clear_canvas(self, reset_image=True):
        """Resets all vector annotations and base image."""
        for item in list(self.history):
            try:
                self.scene.removeItem(item)
            except RuntimeError:
                pass
        self.history.clear()
        self.redo_stack.clear()
        if reset_image:
            self.base_image = None
            if self.bg_pixmap_item:
                try:
                    self.scene.removeItem(self.bg_pixmap_item)
                except RuntimeError:
                    pass
                self.bg_pixmap_item = None
        self.selection_box.update_target()
        if self.on_draw_callback:
            self.on_draw_callback()

    def get_baked_image(self):
        """Renders base screenshot plus all vector scene items onto a full-res PIL Image."""
        if not self.base_image:
            return Image.new("RGBA", (800, 600), (255, 255, 255, 255))

        w, h = self.base_image.width, self.base_image.height
        target_img = QImage(w, h, QImage.Format.Format_RGBA8888)
        target_img.fill(Qt.GlobalColor.transparent)

        self.scene.clearSelection()
        self.selection_box.hide()
        if getattr(self, 'crop_overlay_item', None):
            try:
                self.crop_overlay_item.hide()
            except RuntimeError:
                self.crop_overlay_item = None

        painter = QPainter(target_img)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform |
            QPainter.RenderHint.TextAntialiasing
        )

        self.scene.render(painter, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        painter.end()

        if getattr(self, 'crop_overlay_item', None):
            try:
                self.crop_overlay_item.show()
            except RuntimeError:
                self.crop_overlay_item = None

        return qimage_to_pil(target_img)
