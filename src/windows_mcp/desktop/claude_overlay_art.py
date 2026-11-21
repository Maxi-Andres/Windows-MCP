"""Fork-only restyle of the AI-control indicator (Maxi-Andres/Windows-MCP).

Loaded by control_overlay_art.py when WINDOWS_MCP_OVERLAY_STYLE=claude, replacing its
bitmap functions with a quieter look that matches the Claude HUD: a thin edge line
instead of a 56 px glow, a small dark Spanish pill instead of the big blue banner,
and a discreet ring with a "Claude" tag instead of the cursor aura.

Same names and signatures as control_overlay_art, so control_overlay.py is untouched.
Keeping this in its own file avoids merge conflicts with upstream releases.
"""

import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from windows_mcp.desktop.overlay_bitmap import premultiplied_bgra

__all__ = [
    "_BORDER", "_CURSOR_SIZE", "_NOTICE_GLOW_PAD", "_RIPPLE_SIZE", "_RIPPLE_FRAMES",
    "_glow_alpha", "_edge_bitmap", "_cursor_bitmap", "_ripple_frames",
    "_notice_bitmap", "_notice_glow_bitmap",
]

_BORDER = 7
_CURSOR_SIZE = 128  # room for the "Claude" tag
_RIPPLE_SIZE = 80
_RIPPLE_FRAMES = 9
_NOTICE_GLOW_PAD = 26
_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

_BLUE = (88, 145, 255)
_AMBER = (245, 166, 35)
_CARD = (22, 24, 31)
_TEXT = (241, 243, 246)
_SUB = (178, 184, 196)

_TITLE = "Claude está usando tu PC"
_HINT_PREFIX = "Mové el mouse o apretá"
_SHORTCUT = "Ctrl + Alt + Shift + Backspace"
_HINT_SUFFIX = "para frenarlo"


def _tone(color):
    """Map upstream's blue/amber to the HUD palette."""
    return _AMBER if color[0] > color[2] else _BLUE


def _font(name, size):
    try:
        return ImageFont.truetype(str(_FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def _aa(size, draw, scale=4):
    """Anti-aliased L mask: draw at `scale`x and downsample."""
    w, h = size
    m = Image.new("L", (w * scale, h * scale), 0)
    draw(ImageDraw.Draw(m), scale)
    return m.resize((w, h), Image.Resampling.LANCZOS)


def _glow_alpha(depth: int, extent: int = _BORDER) -> int:
    """A crisp 2 px line at the screen edge with a short soft falloff inward."""
    if depth >= extent - 1:
        return 0
    if depth < 2:
        return 205
    return round(120 * (1 - (depth - 1) / (extent - 2)) ** 2)


def _edge_bitmap(width: int, height: int, side: str, color: tuple[int, int, int]) -> bytes:
    color = _tone(color)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    extent = min(_BORDER, height if side in ("top", "bottom") else width)
    corner_width = min(extent, width // 2)
    for depth in range(extent):
        alpha = _glow_alpha(depth, extent)
        if side in ("top", "bottom"):
            y = depth if side == "top" else height - 1 - depth
            draw.line((0, y, width - 1, y), fill=(*color, alpha))
            for side_depth in range(corner_width):
                corner_alpha = _glow_alpha(min(depth, side_depth), extent)
                draw.point((side_depth, y), fill=(*color, corner_alpha))
                draw.point((width - 1 - side_depth, y), fill=(*color, corner_alpha))
        elif side == "left":
            draw.line((depth, 0, depth, height - 1), fill=(*color, alpha))
        else:
            x = width - 1 - depth
            draw.line((x, 0, x, height - 1), fill=(*color, alpha))
    return premultiplied_bgra(image, 1.0)


def _cursor_bitmap(color: tuple[int, int, int]) -> bytes:
    """Thin ring around the hotspot plus a small 'Claude' tag."""
    color = _tone(color)
    size = _CURSOR_SIZE
    c = size / 2
    image = Image.new("RGBA", (size, size), (*color, 0))
    r = 15
    ring = _aa((size, size), lambda d, k: d.ellipse(
        ((c - r) * k, (c - r) * k, (c + r) * k, (c + r) * k), outline=255, width=2 * k))
    fill = _aa((size, size), lambda d, k: d.ellipse(
        ((c - r) * k, (c - r) * k, (c + r) * k, (c + r) * k), fill=255))
    alpha = ImageChops.add(ring.point(lambda v: v * 200 // 255), fill.point(lambda v: v * 28 // 255))
    image.putalpha(alpha)
    # tag above-right of the ring
    font = _font("seguisb.ttf", 11)
    label = "Claude"
    tw = math.ceil(font.getlength(label))
    w, h = tw + 12, 17
    left, top = int(c + 10), int(c - r - h + 2)
    tag = _aa((size, size), lambda d, k: d.rounded_rectangle(
        (left * k, top * k, (left + w) * k, (top + h) * k), radius=h / 2 * k, fill=255))
    tag_layer = Image.new("RGBA", (size, size), (*color, 0))
    tag_layer.putalpha(tag.point(lambda v: v * 235 // 255))
    image.alpha_composite(tag_layer)
    ImageDraw.Draw(image).text((left + w / 2, top + h / 2), label, font=font,
                               fill=(255, 255, 255, 255), anchor="mm")
    return premultiplied_bgra(image, 1.0)


def _ripple_frames(color: tuple[int, int, int]) -> list[bytes]:
    color = _tone(color)
    scale = 4
    size = _RIPPLE_SIZE * scale
    frames = []
    for index in range(_RIPPLE_FRAMES):
        p = (index + 1) / _RIPPLE_FRAMES
        radius = (8 + (1 - (1 - p) ** 3) * (_RIPPLE_SIZE / 2 - 12)) * scale
        image = Image.new("RGBA", (size, size), (*color, 0))
        ImageDraw.Draw(image).ellipse(
            (size / 2 - radius, size / 2 - radius, size / 2 + radius, size / 2 + radius),
            outline=(*color, round(220 * (1 - p) ** 1.2)), width=2 * scale)
        image = image.resize((_RIPPLE_SIZE, _RIPPLE_SIZE), Image.Resampling.LANCZOS)
        frames.append(premultiplied_bgra(image, 1.0))
    return frames


def _notice_bitmap(screen_width: int) -> tuple[int, int, bytes] | None:
    """Dark pill: pulse dot · title · how to take over (with a key badge)."""
    title_f = _font("seguisb.ttf", 15)
    hint_f = _font("segoeui.ttf", 13)
    key_f = _font("seguisb.ttf", 12)
    pad, gap = 18, 12
    dot = 10
    title_w = math.ceil(title_f.getlength(_TITLE))
    pre_w = math.ceil(hint_f.getlength(_HINT_PREFIX))
    key_w = math.ceil(key_f.getlength(_SHORTCUT)) + 16
    suf_w = math.ceil(hint_f.getlength(_HINT_SUFFIX))
    sep_w = 1
    width = pad + dot + 10 + title_w + gap + sep_w + gap + pre_w + 7 + key_w + 7 + suf_w + pad
    height = 44
    if width > screen_width - 32:
        return None

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    body = _aa((width, height), lambda d, k: d.rounded_rectangle(
        (0, 0, width * k - 1, height * k - 1), radius=height / 2 * k, fill=255))
    card = Image.new("RGBA", (width, height), _CARD + (0,))
    card.putalpha(body.point(lambda v: v * 242 // 255))
    image.alpha_composite(card)
    inner = _aa((width, height), lambda d, k: d.rounded_rectangle(
        (k, k, width * k - 1 - k, height * k - 1 - k), radius=(height / 2 - 1) * k, fill=255))
    hair = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    hair.putalpha(ImageChops.subtract(body, inner).point(lambda v: v * 34 // 255))
    image.alpha_composite(hair)

    d = ImageDraw.Draw(image)
    cy = height / 2
    x = pad
    # status dot with a soft halo
    halo = _aa((width, height), lambda dd, k: dd.ellipse(
        ((x - 3) * k, (cy - dot / 2 - 3) * k, (x + dot + 3) * k, (cy + dot / 2 + 3) * k), fill=255))
    halo_layer = Image.new("RGBA", (width, height), _BLUE + (0,))
    halo_layer.putalpha(halo.point(lambda v: v * 60 // 255))
    image.alpha_composite(halo_layer)
    core = _aa((width, height), lambda dd, k: dd.ellipse(
        (x * k, (cy - dot / 2) * k, (x + dot) * k, (cy + dot / 2) * k), fill=255))
    core_layer = Image.new("RGBA", (width, height), _BLUE + (0,))
    core_layer.putalpha(core)
    image.alpha_composite(core_layer)
    d = ImageDraw.Draw(image)
    x += dot + 10
    d.text((x, cy), _TITLE, font=title_f, fill=_TEXT + (255,), anchor="lm")
    x += title_w + gap
    d.line((x, cy - 9, x, cy + 9), fill=(58, 62, 72, 255), width=1)
    x += sep_w + gap
    d.text((x, cy), _HINT_PREFIX, font=hint_f, fill=_SUB + (255,), anchor="lm")
    x += pre_w + 7
    kh = 22
    badge = _aa((width, height), lambda dd, k: dd.rounded_rectangle(
        (x * k, (cy - kh / 2) * k, (x + key_w) * k, (cy + kh / 2) * k), radius=6 * k, fill=255))
    badge_layer = Image.new("RGBA", (width, height), (52, 56, 66, 0))
    badge_layer.putalpha(badge)
    image.alpha_composite(badge_layer)
    d = ImageDraw.Draw(image)
    d.text((x + key_w / 2, cy), _SHORTCUT, font=key_f, fill=_TEXT + (255,), anchor="mm")
    x += key_w + 7
    d.text((x, cy), _HINT_SUFFIX, font=hint_f, fill=_SUB + (255,), anchor="lm")
    return width, height, premultiplied_bgra(image, 1.0)


def _notice_glow_bitmap(
    width: int, height: int, color: tuple[int, int, int], pad: int = _NOTICE_GLOW_PAD
) -> bytes:
    """Soft drop shadow with a faint accent tint, instead of a bright aura."""
    size = (width + 2 * pad, height + 2 * pad)
    shape = Image.new("L", size, 0)
    ImageDraw.Draw(shape).rounded_rectangle(
        (pad, pad + 4, pad + width, pad + height + 4), radius=height // 2, fill=150)
    shadow = shape.filter(ImageFilter.GaussianBlur(pad / 2.2))
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    dark = Image.new("RGBA", size, (0, 0, 0, 0))
    dark.putalpha(shadow)
    out.alpha_composite(dark)
    tint = Image.new("RGBA", size, _tone(color) + (0,))
    tint.putalpha(shadow.point(lambda v: v * 40 // 255))
    out.alpha_composite(tint)
    return premultiplied_bgra(out, 1.0)
