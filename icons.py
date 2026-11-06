import math
import re
from PIL import Image, ImageDraw, ImageChops

icon_cache = {}
_SUPERSAMPLE = 4  # render at 4x then downsample for smooth anti-aliased edges

# ---------------------------------------------------------------------------
# Real Material Design icons (MDI) — single filled SVG paths (viewBox 0 0 24 24)
# sourced via the `better-icons` tool from Iconify. Each path is rasterized by
# _mdi_tile() and tinted with the passed theme color, so icons keep adapting to
# Light (dark-on-light) and Dark (light-on-dark) themes exactly like before.
# ---------------------------------------------------------------------------
MDI_ICONS = {
    "camera": "M4 4h3l2-2h6l2 2h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2m8 3a5 5 0 0 0-5 5a5 5 0 0 0 5 5a5 5 0 0 0 5-5a5 5 0 0 0-5-5m0 2a3 3 0 0 1 3 3a3 3 0 0 1-3 3a3 3 0 0 1-3-3a3 3 0 0 1 3-3",
    "pointer": "M13.64 21.97a.99.99 0 0 1-1.33-.47l-2.18-4.74l-2.51 2.02c-.17.14-.38.22-.62.22a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1c.24 0 .47.09.64.23l.01-.01l11.49 9.64a1.001 1.001 0 0 1-.44 1.75l-3.16.62l2.2 4.73c.26.5.02 1.09-.48 1.32z",
    "pencil": "M20.71 7.04c.39-.39.39-1.04 0-1.41l-2.34-2.34c-.37-.39-1.02-.39-1.41 0l-1.84 1.83l3.75 3.75M3 17.25V21h3.75L17.81 9.93l-3.75-3.75z",
    "highlighter": "M18.5 1.15c-.53 0-1.04.19-1.43.58l-5.81 5.82l5.65 5.65l5.82-5.81c.77-.78.77-2.04 0-2.83l-2.84-2.83c-.39-.39-.89-.58-1.39-.58M10.3 8.5l-5.96 5.96c-.78.78-.78 2.04.02 2.85C3.14 18.54 1.9 19.77.67 21h5.66l.86-.86c.78.76 2.03.75 2.81-.02l5.95-5.96",
    "eraser": "m16.24 3.56l4.95 4.94c.78.79.78 2.05 0 2.84L12 20.53a4.01 4.01 0 0 1-5.66 0L2.81 17c-.78-.79-.78-2.05 0-2.84l10.6-10.6c.79-.78 2.05-.78 2.83 0M4.22 15.58l3.54 3.53c.78.79 2.04.79 2.83 0l3.53-3.53l-4.95-4.95z",
    "text": "m18.5 4l1.16 4.35l-.96.26c-.45-.87-.91-1.74-1.44-2.18C16.73 6 16.11 6 15.5 6H13v10.5c0 .5 0 1 .33 1.25c.34.25 1 .25 1.67.25v1H9v-1c.67 0 1.33 0 1.67-.25c.33-.25.33-.75.33-1.25V6H8.5c-.61 0-1.23 0-1.76.43c-.53.44-.99 1.31-1.44 2.18l-.96-.26L5.5 4z",
    "crop": "M7 17V1H5v4H1v2h4v10a2 2 0 0 0 2 2h10v4h2v-4h4v-2m-6-2h2V7a2 2 0 0 0-2-2H9v2h8z",
    "line": "M19 13H5v-2h14z",
    "arrow": "M5 17.59L15.59 7H9V5h10v10h-2V8.41L6.41 19z",
    "rectangle": "M4 6v13h16V6zm14 11H6V8h12z",
    "circle": "M12 20a8 8 0 0 1-8-8a8 8 0 0 1 8-8a8 8 0 0 1 8 8a8 8 0 0 1-8 8m0-18A10 10 0 0 0 2 12a10 10 0 0 0 10 10a10 10 0 0 0 10-10A10 10 0 0 0 12 2",
    "save": "M15 9H5V5h10m-3 14a3 3 0 0 1-3-3a3 3 0 0 1 3-3a3 3 0 0 1 3 3a3 3 0 0 1-3 3m5-16H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7z",
    "copy": "M19 21H8V7h11m0-2H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2m-3-4H4a2 2 0 0 0-2 2v14h2V3h12z",
    "clear": "M19 4h-3.5l-1-1h-5l-1 1H5v2h14M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6z",
    "zoom_in": "M9 2a7 7 0 0 1 7 7c0 1.57-.5 3-1.39 4.19l.8.81H16l6 6l-2 2l-6-6v-.59l-.81-.8A6.9 6.9 0 0 1 9 16a7 7 0 0 1-7-7a7 7 0 0 1 7-7M8 5v3H5v2h3v3h2v-3h3V8h-3V5z",
    "zoom_out": "M9 2a7 7 0 0 1 7 7c0 1.57-.5 3-1.39 4.19l.8.81H16l6 6l-2 2l-6-6v-.59l-.81-.8A6.9 6.9 0 0 1 9 16a7 7 0 0 1-7-7a7 7 0 0 1 7-7M5 8v2h8V8z",
    "redo": "M18.4 10.6C16.55 9 14.15 8 11.5 8c-4.65 0-8.58 3.03-9.96 7.22L3.9 16a8 8 0 0 1 7.6-5.5c1.95 0 3.73.72 5.12 1.88L13 16h9V7z",
    "undo": "M12.5 8c-2.65 0-5.05 1-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88c3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8",
    "settings": "M12 15.5A3.5 3.5 0 0 1 8.5 12A3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5a3.5 3.5 0 0 1-3.5 3.5m7.43-2.53c.04-.32.07-.64.07-.97s-.03-.66-.07-1l2.11-1.63c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34-.07.67-.07 1s.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64z",
    "collage": "M3 3h7v7H3V3m1 1v5h5V4H4m10-1h7v7h-7V3m1 1v5h5V4h-5M3 13h7v7H3v-7m1 1v5h5v-5H4m10-1h7v7h-7v-7m1 1v5h5v-5h-5z",
    "folder": "M10 4H4c-1.11 0-2 .89-2 2v12c0 1.1.89 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
    "folder_open": "M19 20H4a2 2 0 0 1-2-2V6c0-1.11.89-2 2-2h6l2 2h7a2 2 0 0 1 2 2H4v10l2.14-8h17.07l-2.28 8.5c-.23.87-1.01 1.5-1.93 1.5",
    "open": "M19 20H4a2 2 0 0 1-2-2V6c0-1.11.89-2 2-2h6l2 2h7a2 2 0 0 1 2 2H4v10l2.14-8h17.07l-2.28 8.5c-.23.87-1.01 1.5-1.93 1.5",
}

# The Select tool button is wired with icon name "pointer"; keep "select" as an alias.
MDI_ICONS["select"] = MDI_ICONS["pointer"]
MDI_ICONS["open_file"] = MDI_ICONS["folder_open"]


# ---------------------------------------------------------------------------
# Minimal SVG path parser ("M/L/H/V/C/S/Q/T/A/Z" + lowercase relatives) that
# flattens curves/arcs into polylines and returns the closed subpaths so they can
# be rasterized with an even-odd (parity) fill — reproducing MDI hole shapes
# (e.g. the donut rings in "circle"/"zoom" and the lens cut-out in "camera").
# ---------------------------------------------------------------------------
def _sample_cubic(x0, y0, x1, y1, x2, y2, x3, y3, steps):
    pts = []
    for k in range(1, steps + 1):
        t = k / steps
        mt = 1 - t
        a, b, c, d = mt ** 3, 3 * mt * mt * t, 3 * mt * t * t, t ** 3
        pts.append((a * x0 + b * x1 + c * x2 + d * x3,
                    a * y0 + b * y1 + c * y2 + d * y3))
    return pts


def _sample_quad(x0, y0, x1, y1, x2, y2, steps):
    pts = []
    for k in range(1, steps + 1):
        t = k / steps
        mt = 1 - t
        pts.append((mt * mt * x0 + 2 * mt * t * x1 + t * t * x2,
                    mt * mt * y0 + 2 * mt * t * y1 + t * t * y2))
    return pts


def _sample_arc(x1, y1, rx, ry, phi, large_arc, sweep, x2, y2):
    """Return linear-sample points along an SVG elliptical arc to (x2, y2)."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi)
    cosphi, sinphi = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cosphi * dx2 + sinphi * dy2
    y1p = -sinphi * dx2 + cosphi * dy2
    rx, ry = abs(rx), abs(ry)
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(num / den, 0.0)) if den else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * (rx * y1p / ry)
    cyp = coef * (-ry * x1p / rx)
    cx = cosphi * cxp - sinphi * cyp + (x1 + x2) / 2.0
    cy = sinphi * cxp + cosphi * cyp + (y1 + y2) / 2.0

    def _ang(ux, uy, vx, vy):
        ln = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / ln))) if ln else 0.0
        return -a if (ux * vy - uy * vx) < 0 else a

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = _ang(1.0, 0.0, ux, uy)
    dtheta = _ang(ux, uy, vx, vy)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    n = max(2, round(abs(dtheta) / (math.pi / 18)))
    pts = []
    for k in range(1, n + 1):
        ang = theta1 + dtheta * k / n
        cA, sA = math.cos(ang), math.sin(ang)
        xp, yp = rx * cA, ry * sA
        pts.append((cosphi * xp - sinphi * yp + cx,
                    sinphi * xp + cosphi * yp + cy))
    return pts


def _parse_to_subpaths(path_d):
    """Flatten an MDI path into closed subpath point lists (24-space).

    Letters and numbers are merged into a single position-sorted stream and walked
    with one cursor, so relative commands resolve against the running current
    point exactly as the SVG spec requires. Repeated coordinate groups after a
    command (e.g. `M x y x2 y2` or `L a b c d`) are handled as continuations.
    """
    merged = []
    for m in re.finditer(r"[A-Za-z]", path_d):
        merged.append((m.start(), 'L', m.group()))
    for m in re.finditer(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", path_d):
        merged.append((m.start(), 'N', m.group()))
    merged.sort(key=lambda x: x[0])

    m = 0  # single cursor into `merged`

    def next_num():
        nonlocal m
        v = float(merged[m][2])
        m += 1
        return v

    def peek_type():
        return merged[m][1] if m < len(merged) else None

    def next_letter():
        nonlocal m
        if m >= len(merged) or merged[m][1] != 'L':
            return None
        c = merged[m][2]
        m += 1
        return c

    subpaths = []
    sub = []
    cur_x = cur_y = 0.0
    sx = sy = 0.0
    ctrl = None
    last_cmd = ""

    def begin(x, y):
        nonlocal sub, sx, sy, cur_x, cur_y
        if sub:
            subpaths.append(sub)
        sub = [(x, y)]
        sx, sy, cur_x, cur_y = x, y, x, y

    def finish_sub():
        nonlocal sub, cur_x, cur_y, sx, sy
        if sub and (abs(sub[0][0] - cur_x) > 1e-6 or abs(sub[0][1] - cur_y) > 1e-6):
            sub.append((sx, sy))
        subpaths.append(sub)
        sub = []
        cur_x, cur_y = sx, sy

    def reflect():
        if ctrl is None:
            return (cur_x, cur_y)
        return (2 * cur_x - ctrl[0], 2 * cur_y - ctrl[1])

    cmd = next_letter()
    while cmd is not None:
        up = cmd.upper()

        if up == 'Z':
            finish_sub()
            ctrl = None
            last_cmd = 'Z'
        elif up == 'M':
            x, y = next_num(), next_num()
            if cmd == 'm':
                x += cur_x
                y += cur_y
            begin(x, y)
            ctrl = None
            last_cmd = 'M'
        elif up == 'L':
            x, y = next_num(), next_num()
            if cmd == 'l':
                x += cur_x
                y += cur_y
            sub.append((x, y))
            cur_x, cur_y = x, y
            ctrl = None
            last_cmd = 'L'
        elif up == 'H':
            x = next_num()
            if cmd == 'h':
                x += cur_x
            sub.append((x, cur_y))
            cur_x = x
            ctrl = None
            last_cmd = 'H'
        elif up == 'V':
            y = next_num()
            if cmd == 'v':
                y += cur_y
            sub.append((cur_x, y))
            cur_y = y
            ctrl = None
            last_cmd = 'V'
        elif up == 'C':
            x1, y1, x2, y2, x, y = (next_num() for _ in range(6))
            if cmd == 'c':
                x1, y1 = x1 + cur_x, y1 + cur_y
                x2, y2 = x2 + cur_x, y2 + cur_y
                x, y = x + cur_x, y + cur_y
            sub.extend(_sample_cubic(cur_x, cur_y, x1, y1, x2, y2, x, y, 32))
            cur_x, cur_y = x, y
            ctrl = (x2, y2)
            last_cmd = 'C'
        elif up == 'S':
            x2, y2, x, y = (next_num() for _ in range(4))
            if cmd == 's':
                x2, y2 = x2 + cur_x, y2 + cur_y
                x, y = x + cur_x, y + cur_y
            x1, y1 = reflect() if last_cmd in ('C', 'S') else (cur_x, cur_y)
            sub.extend(_sample_cubic(cur_x, cur_y, x1, y1, x2, y2, x, y, 32))
            cur_x, cur_y = x, y
            ctrl = (x2, y2)
            last_cmd = 'S'
        elif up == 'Q':
            x1, y1, x, y = (next_num() for _ in range(4))
            if cmd == 'q':
                x1, y1 = x1 + cur_x, y1 + cur_y
                x, y = x + cur_x, y + cur_y
            sub.extend(_sample_quad(cur_x, cur_y, x1, y1, x, y, 24))
            cur_x, cur_y = x, y
            ctrl = (x1, y1)
            last_cmd = 'Q'
        elif up == 'T':
            x, y = next_num(), next_num()
            if cmd == 't':
                x, y = x + cur_x, y + cur_y
            x1, y1 = reflect() if last_cmd in ('Q', 'T') else (cur_x, cur_y)
            sub.extend(_sample_quad(cur_x, cur_y, x1, y1, x, y, 24))
            cur_x, cur_y = x, y
            ctrl = (x1, y1)
            last_cmd = 'T'
        elif up == 'A':
            rx, ry, phi, la, sw, x, y = (next_num() for _ in range(7))
            if cmd == 'a':
                x, y = x + cur_x, y + cur_y
            sub.extend(_sample_arc(cur_x, cur_y, rx, ry, phi, int(la), int(sw), x, y))
            cur_x, cur_y = x, y
            ctrl = None
            last_cmd = 'A'
        else:
            break  # unknown command letter; stop safely

        # Next token: if a number, the same command repeats (M continues as L);
        # if a letter, that letter starts the next command.
        if peek_type() == 'N':
            if up == 'M':
                cmd = 'L'
            # otherwise keep `cmd` (e.g. 'c', 'l', 's' ...) for the next group
        else:
            cmd = next_letter()

    if sub:
        finish_sub()
    return subpaths


def _evenodd_mask(path_d, size):
    """Rasterize an MDI path into a binary mask using even-odd (parity) fill."""
    subpaths = _parse_to_subpaths(path_d)
    sx_scale = size[0] / 24.0
    sy_scale = size[1] / 24.0
    acc = None
    for pts in subpaths:
        scaled = [(round(x * sx_scale), round(y * sy_scale)) for x, y in pts]
        m = Image.new("1", size, 0)
        ImageDraw.Draw(m).polygon(scaled, fill=1)
        acc = m if acc is None else ImageChops.logical_xor(acc, m)
    return acc if acc is not None else Image.new("1", size, 0)


def _mdi_tile(path_d, color, size):
    """Render an MDI path to a full RGBA tile of `size`, supersampled for AA edges."""
    target = (int(size[0]), int(size[1]))
    ws = (max(1, target[0] * _SUPERSAMPLE), max(1, target[1] * _SUPERSAMPLE))
    mask = _evenodd_mask(path_d, ws).convert("L").resize(target, Image.LANCZOS)
    colored = Image.new("RGBA", target, color)
    tile = Image.new("RGBA", target, (0, 0, 0, 0))
    tile.paste(colored, (0, 0), mask)
    return tile


def draw_vector_icon(draw, name, color, size):
    """Draws a theme-adaptable icon for each toolbar tool.

    Every glyph is rasterized from a real Material Design (MDI) SVG path with a
    single ``color`` so it adapts to Light (dark on light) and Dark (light on
    dark) themes.
    """
    path_d = MDI_ICONS.get(name)
    if path_d is None:
        return
    tile = _mdi_tile(path_d, color, size)
    # Paste the rendered tile (with its alpha) onto the caller's image.
    draw._image.paste(tile, (0, 0), tile)



def pil_to_qpixmap(pil_img):
    """Converts a PIL RGBA Image to a PySide6 QPixmap."""
    from PySide6.QtGui import QImage, QPixmap
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


def get_qicon(name, color="#333333", size=(24, 24)):
    """Generates and returns a PySide6 QIcon for the requested icon in Light/Dark themes."""
    from PySide6.QtGui import QIcon
    key = ("qicon", name, color, size)
    if key in icon_cache:
        return icon_cache[key]

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_vector_icon(draw, name, color, size)

    pixmap = pil_to_qpixmap(img)
    qicon = QIcon(pixmap)
    icon_cache[key] = qicon
    return qicon


def get_qpixmap(name, color="#333333", size=(24, 24)):
    """Generates and returns a PySide6 QPixmap for the requested icon in Light/Dark themes."""
    key = ("qpixmap", name, color, size)
    if key in icon_cache:
        return icon_cache[key]

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_vector_icon(draw, name, color, size)

    pixmap = pil_to_qpixmap(img)
    icon_cache[key] = pixmap
    return pixmap

