"""Always-on-top HUD that shows what Claude is doing on the desktop.

Fed by hook.py through %LOCALAPPDATA%\\claude-hud\\actions.jsonl (or $CLAUDE_HUD_DIR).
A per-pixel-alpha layered Win32 window drawn with Pillow: rounded card, soft shadow,
Windows 11 icons, pulse while Claude acts, slide/fade animations. Click-through,
never takes focus and is excluded from screen captures, so it never gets in the way
of Claude's own screenshots.

States: full card (newest action + history) -> compact pill after COMPACT_SECS idle
-> hidden after HIDE_SECS -> process exits after EXIT_SECS (the hook relaunches it).

    pythonw hud.pyw                 run the HUD
    python  hud.pyw --preview out.png   render every state to an image (no window)

Needs Pillow + numpy: run it with the windows-mcp tool's Python (install.ps1 does).
"""

import ctypes
import json
import math
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- config

DIR = Path(os.environ.get("CLAUDE_HUD_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "claude-hud")
LOG = DIR / "actions.jsonl"
BEAT = DIR / "heartbeat"


def _env_secs(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


ACTIVE_SECS = _env_secs("CLAUDE_HUD_ACTIVE_SECS", 4)  # "mirando/usando" + pulse after an action
COMPACT_SECS = _env_secs("CLAUDE_HUD_COMPACT_SECS", 30)  # then collapse to a pill
HIDE_SECS = _env_secs("CLAUDE_HUD_HIDE_SECS", 120)  # then hide
EXIT_SECS = _env_secs("CLAUDE_HUD_EXIT_SECS", 900)  # then quit
HISTORY = 4  # older actions listed under the newest one

KINDS = {
    "look": ((245, 166, 35), "Claude está mirando tu pantalla"),
    "act": ((88, 145, 255), "Claude está usando tu PC"),
    "danger": ((244, 91, 91), "Claude está haciendo algo importante"),
    "info": ((160, 172, 192), "Claude está trabajando"),
}
IDLE_COLOR = (120, 128, 142)

# Segoe Fluent Icons (Win 11) / Segoe MDL2 Assets (Win 10) code points
GLYPHS = {
    "look": "\ue890", "click": "\ue8b0", "type": "\ue765", "key": "\ue92e",
    "scroll": "\uec8f", "move": "\ue7c2", "app": "\ue8a7", "window": "\ue7c4",
    "kill": "\ue711", "list": "\ue8fd", "clipboard": "\ue77f", "web": "\ue774",
    "notify": "\uea8f", "wait": "\ue916", "info": "\ue946", "display": "\ue7f4",
    "select": "\uf0e2",
}
KIND_GLYPH = {"look": "look", "act": "click", "danger": "kill", "info": "info"}

CARD_RGB, CARD_ALPHA = (22, 24, 31), 240
TEXT = (241, 243, 246)
SUB = (178, 184, 196)
DIM = (128, 135, 149)
FAINT = (96, 103, 116)
SEPARATOR = (44, 47, 56, 255)

# layout, in 96-dpi pixels
W = 404  # card width
PAD = 16
ICON_D = 40
HEAD_H = 72
ROW_H = 27
RADIUS = 18
MARGIN = 22  # transparent space around the card for the shadow
SCREEN_GAP = 18  # distance from the work-area corner
SS = 4  # supersampling for anti-aliased shapes

FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(str(FONT_DIR / n), max(1, round(size)))
        except OSError:
            continue
    return ImageFont.load_default()


def ease_out(p):
    return 1 - (1 - p) ** 3


def ago(secs):
    secs = int(secs)
    if secs < 5:
        return "ahora"
    if secs < 60:
        return f"hace {secs} s"
    if secs < 3600:
        return f"hace {secs // 60} min"
    return f"hace {secs // 3600} h"


def fit(text, font, max_w):
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def event_color(ev):
    return KINDS.get(ev.get("kind"), KINDS["info"])[0]


def event_glyph(ev):
    return GLYPHS.get(ev.get("type")) or GLYPHS[KIND_GLYPH.get(ev.get("kind"), "info")]


# ---------------------------------------------------------------- drawing


class Painter:
    """Renders HUD states to RGBA images at a given DPI scale."""

    def __init__(self, scale=1.0):
        self.s = scale
        px = self.px
        self.f_title = _font(["seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"], px(15))
        self.f_sub = _font(["segoeui.ttf"], px(13.5))
        self.f_row = _font(["segoeui.ttf"], px(12.5))
        self.f_small = _font(["segoeui.ttf"], px(11.5))
        self.f_icon = _font(["SegoeIcons.ttf", "segmdl2.ttf"], px(18))
        self.f_icon_small = _font(["SegoeIcons.ttf", "segmdl2.ttf"], px(12.5))

    def px(self, v):
        return int(round(v * self.s))

    # --- primitives
    def _aa_mask(self, size, draw):
        w, h = size
        m = Image.new("L", (w * SS, h * SS), 0)
        draw(ImageDraw.Draw(m), SS)
        return m.resize((w, h), Image.LANCZOS)

    def _fill(self, img, mask, rgb, alpha=255):
        layer = Image.new("RGBA", img.size, rgb + (0,))
        layer.putalpha(mask.point(lambda v: v * alpha // 255) if alpha != 255 else mask)
        img.alpha_composite(layer)

    def _card(self, size, box, radius, accent):
        """Shadow + card + hairline border + accent glow. Returns (img, border_mask)."""
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        x0, y0, x1, y1 = box
        # soft shadow
        sh = Image.new("L", size, 0)
        ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + self.px(6), x1, y1 + self.px(6)), radius, fill=120)
        sh = sh.filter(ImageFilter.GaussianBlur(self.px(12)))
        self._fill(img, sh, (0, 0, 0))
        # card body
        outer = self._aa_mask(size, lambda d, k: d.rounded_rectangle(
            (x0 * k, y0 * k, x1 * k - 1, y1 * k - 1), radius * k, fill=255))
        self._fill(img, outer, CARD_RGB, CARD_ALPHA)
        # accent glow behind the icon, clipped to the card
        if accent:
            cx, cy = x0 + self.px(PAD + ICON_D / 2), y0 + self.px(HEAD_H / 2)
            glow = Image.new("L", size, 0)
            r = self.px(70)
            ImageDraw.Draw(glow).ellipse((cx - r, cy - r, cx + r, cy + r), fill=46)
            glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(self.px(34))), outer)
            self._fill(img, glow, accent)
        # hairline border
        t = max(1, self.px(1))
        inner = self._aa_mask(size, lambda d, k: d.rounded_rectangle(
            ((x0 + t) * k, (y0 + t) * k, (x1 - t) * k - 1, (y1 - t) * k - 1), (radius - t) * k, fill=255))
        border = ImageChops.subtract(outer, inner)
        self._fill(img, border, (255, 255, 255), 30)
        return img, border

    def _circle(self, img, center, r, rgb, alpha):
        cx, cy = center
        mask = self._aa_mask(img.size, lambda d, k: d.ellipse(
            ((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=255))
        self._fill(img, mask, rgb, alpha)

    # --- states
    def full(self, events, now, active):
        """Card with the newest action on top and up to HISTORY older ones."""
        px = self.px
        newest = events[-1]
        older = list(reversed(events[:-1]))[:HISTORY]
        color = event_color(newest) if active else IDLE_COLOR
        title = KINDS.get(newest.get("kind"), KINDS["info"])[1] if active else "Última acción de Claude"

        card_h = HEAD_H + (10 + len(older) * ROW_H + 8 if older else 0)
        size = (px(W + 2 * MARGIN), px(card_h + 2 * MARGIN))
        box = (px(MARGIN), px(MARGIN), px(MARGIN + W), px(MARGIN + card_h))
        img, border = self._card(size, box, px(RADIUS), color if active else None)
        d = ImageDraw.Draw(img)
        x0, y0 = box[0], box[1]

        # icon bubble
        center = (x0 + px(PAD + ICON_D / 2), y0 + px(HEAD_H / 2))
        self._circle(img, center, px(ICON_D / 2), color, 60 if active else 40)
        d.text(center, event_glyph(newest), font=self.f_icon, fill=color, anchor="mm")

        # title, time, subtitle
        tx = x0 + px(PAD + ICON_D + 13)
        right = x0 + px(W - PAD)
        when = ago(now - newest["t"])
        d.text((right, y0 + px(19)), when, font=self.f_small, fill=DIM, anchor="rt")
        title_w = right - tx - self.f_small.getlength(when) - px(10)
        d.text((tx, y0 + px(16)), fit(title, self.f_title, title_w), font=self.f_title,
               fill=TEXT, anchor="lt")
        d.text((tx, y0 + px(40)), fit(newest["text"], self.f_sub, right - tx), font=self.f_sub,
               fill=SUB, anchor="lt")

        # history
        if older:
            sep_y = y0 + px(HEAD_H)
            # opaque: ImageDraw replaces pixels instead of blending, so no alpha here
            d.line((x0 + px(PAD), sep_y, right, sep_y), fill=SEPARATOR, width=max(1, px(1)))
            for i, ev in enumerate(older):
                cy = sep_y + px(10 + i * ROW_H + ROW_H / 2)
                d.text((x0 + px(PAD + 10), cy), event_glyph(ev), font=self.f_icon_small,
                       fill=tuple(int(c * 0.8) for c in event_color(ev)), anchor="mm")
                stamp = time.strftime("%H:%M:%S", time.localtime(ev["t"]))
                d.text((right, cy), stamp, font=self.f_small, fill=FAINT, anchor="rm")
                row_w = right - self.f_small.getlength(stamp) - px(12) - (x0 + px(PAD + 30))
                d.text((x0 + px(PAD + 30), cy), fit(ev["text"], self.f_row, row_w), font=self.f_row,
                       fill=DIM, anchor="lm")
        return img, border, center, color

    def compact(self, events, now):
        """Small pill: 'Claude · última acción hace 2 min'."""
        px = self.px
        text = f"Claude · última acción {ago(now - events[-1]['t'])}"
        h = 36
        w = int(PAD + 10 + 10 + self.f_row.getlength(text) / self.s + PAD)
        size = (px(w + 2 * MARGIN), px(h + 2 * MARGIN))
        box = (px(MARGIN), px(MARGIN), px(MARGIN + w), px(MARGIN + h))
        img, border = self._card(size, box, px(h / 2), None)
        d = ImageDraw.Draw(img)
        cy = box[1] + px(h / 2)
        self._circle(img, (box[0] + px(PAD + 4), cy), px(4), IDLE_COLOR, 255)
        d.text((box[0] + px(PAD + 18), cy), text, font=self.f_row, fill=SUB, anchor="lm")
        return img, border, None, IDLE_COLOR

    # --- per-frame overlays
    def pulse(self, img, center, color, phase):
        """Two expanding rings around the icon bubble."""
        px = self.px
        r0 = ICON_D / 2
        for p in (phase % 1.0, (phase + 0.5) % 1.0):
            r = px(r0 + 10 * ease_out(p))
            alpha = int(150 * (1 - p) ** 1.5)
            if alpha <= 0:
                continue
            w = max(1, px(2))
            cx, cy = center
            pad = r + w + 2
            patch_box = (cx - pad, cy - pad, cx + pad, cy + pad)
            size = (2 * pad, 2 * pad)
            mask = self._aa_mask(size, lambda d, k: d.ellipse(
                ((pad - r) * k, (pad - r) * k, (pad + r) * k, (pad + r) * k), outline=255, width=w * k))
            patch = Image.new("RGBA", size, color + (0,))
            patch.putalpha(mask.point(lambda v: v * alpha // 255))
            img.alpha_composite(patch, (patch_box[0], patch_box[1]))

    def flash(self, img, border, color, amount):
        """Light up the card border in the accent color (new action)."""
        if amount <= 0:
            return
        layer = Image.new("RGBA", img.size, color + (0,))
        layer.putalpha(border.point(lambda v: int(v * 230 * amount) // 255))
        img.alpha_composite(layer)


# ---------------------------------------------------------------- data


def read_events(n=HISTORY + 1):
    try:
        with LOG.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-n:]:
        try:
            ev = json.loads(line)
            if "t" in ev and "text" in ev:
                events.append(ev)
        except ValueError:
            pass
    return events


# ---------------------------------------------------------------- Win32 window

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.restype = wintypes.HANDLE

WS_POPUP = 0x80000000
WS_EX = 0x00080000 | 0x00000020 | 0x00000080 | 0x00000008 | 0x08000000  # LAYERED|TRANSPARENT|TOOLWINDOW|TOPMOST|NOACTIVATE
HWND_TOPMOST = wintypes.HWND(-1)
SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE|NOMOVE|NOACTIVATE


def work_area():
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA (primary monitor)
    return r


class Window:
    def __init__(self):
        self._proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc,
                         hInstance=hinst, lpszClassName="ClaudeWindowsHUD")
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(WS_EX, "ClaudeWindowsHUD", "Claude HUD", WS_POPUP,
                                           0, 0, 1, 1, None, None, hinst, None)
        if not os.environ.get("CLAUDE_HUD_VISIBLE_IN_CAPTURE"):
            user32.SetWindowDisplayAffinity(self.hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
        self.visible = False

    def present(self, img, x, y, alpha=1.0):
        w, h = img.size
        a = np.asarray(img, dtype=np.uint16)
        bgra = np.empty((h, w, 4), dtype=np.uint8)
        al = a[..., 3]
        bgra[..., 0] = a[..., 2] * al // 255  # premultiplied, BGRA order
        bgra[..., 1] = a[..., 1] * al // 255
        bgra[..., 2] = a[..., 0] * al // 255
        bgra[..., 3] = al
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                               biPlanes=1, biBitCount=32, biCompression=0)
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, bgra.tobytes(), w * h * 4)
        old = gdi32.SelectObject(mem, hbmp)
        blend = BLENDFUNCTION(0, 0, max(0, min(255, int(alpha * 255))), 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
                                   ctypes.byref(wintypes.SIZE(w, h)), mem,
                                   ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
        if not self.visible:
            user32.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
            self.visible = True

    def hide(self):
        if self.visible:
            user32.ShowWindow(self.hwnd, 0)
            self.visible = False

    def keep_on_top(self):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)

    def pump(self):
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# ---------------------------------------------------------------- app


class HUD:
    APPEAR = 0.32
    FADE_OUT = 0.35
    FLASH = 0.9
    PULSE_PERIOD = 1.6

    def __init__(self):
        try:
            user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4))  # per-monitor v2
        except Exception:
            pass
        scale = user32.GetDpiForSystem() / 96 if hasattr(user32, "GetDpiForSystem") else 1.0
        self.painter = Painter(scale)
        self.win = Window()
        self.events = []
        self.stat = None
        self.last_newest = None
        self.mode = "hidden"
        self.appear_t0 = 0.0
        self.fade_t0 = None
        self.flash_t0 = 0.0
        self.base_key = None
        self.base = None
        self.last_beat = 0.0
        self.last_top = 0.0
        self.started = time.time()

    def poll(self, now):
        try:
            st = LOG.stat()
            stat = (st.st_mtime_ns, st.st_size)
        except OSError:
            stat = None
        if stat != self.stat:
            self.stat = stat
            self.events = read_events()
        newest = self.events[-1]["t"] if self.events else None
        if newest != self.last_newest:
            if self.last_newest is not None or (newest and now - newest < ACTIVE_SECS):
                self.flash_t0 = now
            self.last_newest = newest

    def target_mode(self, idle):
        if idle < COMPACT_SECS:
            return "full"
        if idle < HIDE_SECS:
            return "compact"
        return "hidden"

    def frame(self, now):
        idle = now - self.events[-1]["t"] if self.events else math.inf
        active = idle < ACTIVE_SECS
        mode = self.target_mode(idle)

        if mode != "hidden" and self.mode == "hidden":
            self.appear_t0 = now
            self.fade_t0 = None
        if mode == "hidden" and self.mode != "hidden" and self.fade_t0 is None:
            self.fade_t0 = now
        if mode != "hidden":
            self.mode = mode

        if mode == "hidden":
            if self.fade_t0 is None:
                return False
            p = (now - self.fade_t0) / self.FADE_OUT
            if p >= 1:
                self.win.hide()
                self.mode = "hidden"
                self.fade_t0 = None
                return False
            self._draw(now, idle, False, alpha=1 - p, lift=0)
            return True

        appear = min(1.0, (now - self.appear_t0) / self.APPEAR)
        flash = max(0.0, 1 - (now - self.flash_t0) / self.FLASH)
        self._draw(now, idle, active, alpha=ease_out(appear), lift=1 - ease_out(appear), flash=flash)
        return active or appear < 1 or flash > 0

    def _draw(self, now, idle, active, alpha, lift, flash=0.0):
        label = ago(idle)
        key = (self.mode, tuple(e["t"] for e in self.events), label, active)
        if key != self.base_key or self.base is None:
            if self.mode == "compact":
                self.base = self.painter.compact(self.events, now)
            else:
                self.base = self.painter.full(self.events, now, active)
            self.base_key = key
        img, border, center, color = self.base
        if active or flash > 0:
            img = img.copy()
            if active and center:
                self.painter.pulse(img, center, color, (now % self.PULSE_PERIOD) / self.PULSE_PERIOD)
            self.painter.flash(img, border, color, ease_out(flash))
        r = work_area()
        p = self.painter
        x = r.right - p.px(SCREEN_GAP) - (img.width - p.px(MARGIN))
        y = r.bottom - p.px(SCREEN_GAP) - (img.height - p.px(MARGIN)) + int(lift * p.px(16))
        self.win.present(img, x, y, alpha)

    def run(self):
        while True:
            now = time.time()
            self.win.pump()
            if now - self.last_beat > 1:
                try:
                    DIR.mkdir(parents=True, exist_ok=True)
                    BEAT.write_text(str(now))
                except OSError:
                    pass
                self.last_beat = now
            if now - self.last_top > 2 and self.win.visible:
                self.win.keep_on_top()
                self.last_top = now
            self.poll(now)
            if self.events and now - self.events[-1]["t"] > EXIT_SECS:
                return
            if not self.events and now - self.started > 60:  # launched but nothing to show
                return
            animating = self.frame(now)
            time.sleep(1 / 45 if animating else 0.15)


# ---------------------------------------------------------------- preview


def preview(path):
    """Render every state onto one image, over a busy background, for design review."""
    now = time.time()
    sample = [
        {"t": now - 40, "type": "app", "kind": "act", "text": "Abriendo Bloc de notas"},
        {"t": now - 31, "type": "click", "kind": "act", "text": "Click en (1280, 720)"},
        {"t": now - 22, "type": "type", "kind": "act", "text": "Escribiendo «Hola Max, esto es una prueba del panel» + Enter"},
        {"t": now - 12, "type": "key", "kind": "act", "text": "Atajo de teclado: ctrl+s"},
    ]
    p = Painter(float(os.environ.get("CLAUDE_HUD_SCALE", 1)))
    shots = [
        ("Mirando la pantalla (activo, con pulso)",
         p.full(sample + [{"t": now - 1, "type": "look", "kind": "look", "text": "Mirando la pantalla"}], now, True), 0.3, 0),
        ("Usando la PC (acción nueva: borde iluminado)",
         p.full(sample[:-1] + [{"t": now - 0.2, "type": "type", "kind": "act", "text": "Escribiendo «hola» + Enter"}], now, True), 0.1, 0.7),
        ("Acción importante",
         p.full(sample + [{"t": now - 1, "type": "kill", "kind": "danger", "text": "Cerrando el proceso notepad.exe"}], now, True), 0.6, 0),
        ("Terminó (inactivo)", p.full(sample + [{"t": now - 9, "type": "wait", "kind": "info", "text": "Esperando 2 s"}], now, False), None, 0),
        ("Primera acción (sin historial)", p.full([{"t": now - 1, "type": "app", "kind": "act", "text": "Abriendo Spotify"}], now, True), 0.45, 0),
        ("Compacto (después de 30 s)", p.compact(sample, now + 60), None, 0),
    ]
    label_f = _font(["seguisb.ttf", "segoeui.ttf"], 16)
    gap = 26
    width = max(s[1][0].width for s in shots) + 2 * gap
    height = sum(s[1][0].height + 30 for s in shots) + 2 * gap
    sheet = Image.new("RGBA", (width, height))
    # busy gradient background, like a wallpaper
    yy, xx = np.mgrid[0:height, 0:width]
    bg = np.stack([60 + 80 * xx / width, 70 + 60 * yy / height, 110 + 70 * (1 - xx / width), np.full_like(xx, 255.0)], -1)
    sheet = Image.fromarray(bg.astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(sheet)
    y = gap
    for label, (img, border, center, color), phase, flash in shots:
        d.text((gap, y), label, font=label_f, fill=(255, 255, 255, 230))
        img = img.copy()
        if phase is not None and center:
            p.pulse(img, center, color, phase)
        p.flash(img, border, color, flash)
        sheet.alpha_composite(img, (gap - p.px(MARGIN) + 6, y + 24 - p.px(MARGIN) + 6))
        y += img.height - 2 * p.px(MARGIN) + 30 + 24
    sheet = sheet.crop((0, 0, width, y + gap))
    sheet.convert("RGB").save(path)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
        sys.exit(0)
    _mutex = kernel32.CreateMutexW(None, False, "Local\\ClaudeWindowsHUD")
    if ctypes.get_last_error() == 183 or kernel32.GetLastError() == 183:  # already running
        sys.exit(0)
    HUD().run()
