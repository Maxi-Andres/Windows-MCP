"""Fork-only restyle of the consent countdown (Maxi-Andres/Windows-MCP).

control_consent.py runs this instead of its Tk dialog when WINDOWS_MCP_OVERLAY_STYLE=claude.
Same contract: show(seconds) returns "allow", "deny" or "timeout". The prompt is a dark card
at the top centre of the primary monitor, in Spanish, matching the Claude HUD: amber status
dot, two buttons, and a bar that shrinks with the countdown. It never takes keyboard focus
(clicks only, like the original), so no key is still held when control begins.

Self-contained on purpose (Pillow + ctypes only): it runs in its own process started with
`python -I`, and loading the windows_mcp package there would pull in the whole server.

    python claude_consent.py 7                 show it (exit code like control_consent)
    python claude_consent.py --preview out.png render frames to an image
"""

import ctypes
import math
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------- look

AMBER = (245, 166, 35)
BLUE = (88, 145, 255)
CARD = (22, 24, 31)
TEXT = (241, 243, 246)
SUB = (178, 184, 196)
DIM = (128, 135, 149)

TITLE = "Claude va a usar tu PC"
BODY = "Si seguís usando la compu sin responder, el control sigue siendo tuyo."
ALLOW = "Dejar ahora"
DENY = "No, ahora no"

W, H = 520, 128  # card, 96-dpi px
MARGIN = 24  # transparent room for the shadow
RADIUS = 18
PAD = 20
BTN_H = 34
SS = 4
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


class Painter:
    def __init__(self, scale=1.0):
        self.s = scale
        self.f_title = _font(["seguisb.ttf", "segoeui.ttf"], self.px(15.5))
        self.f_body = _font(["segoeui.ttf"], self.px(13))
        self.f_btn = _font(["seguisb.ttf", "segoeui.ttf"], self.px(13))
        self.f_time = _font(["segoeui.ttf"], self.px(12.5))
        self.size = (self.px(W + 2 * MARGIN), self.px(H + 2 * MARGIN))
        self._base = self._render_base()

    def px(self, v):
        return int(round(v * self.s))

    def _aa(self, draw):
        w, h = self.size
        m = Image.new("L", (w * SS, h * SS), 0)
        draw(ImageDraw.Draw(m), SS)
        return m.resize((w, h), Image.LANCZOS)

    def _fill(self, img, mask, rgb, alpha=255):
        layer = Image.new("RGBA", img.size, rgb + (0,))
        layer.putalpha(mask if alpha == 255 else mask.point(lambda v: v * alpha // 255))
        img.alpha_composite(layer)

    def card_box(self):
        return (self.px(MARGIN), self.px(MARGIN), self.px(MARGIN + W), self.px(MARGIN + H))

    def buttons(self):
        """Hit boxes in window pixels: {"allow": (x0, y0, x1, y1), "deny": ...}."""
        x0, y0, x1, y1 = self.card_box()
        by1 = y1 - self.px(PAD)
        by0 = by1 - self.px(BTN_H)
        allow_w = self.px(24) + int(self.f_btn.getlength(ALLOW))
        deny_w = self.px(24) + int(self.f_btn.getlength(DENY))
        ax1 = x1 - self.px(PAD)
        ax0 = ax1 - allow_w
        dx1 = ax0 - self.px(10)
        dx0 = dx1 - deny_w
        return {"allow": (ax0, by0, ax1, by1), "deny": (dx0, by0, dx1, by1)}

    def _render_base(self):
        img = Image.new("RGBA", self.size, (0, 0, 0, 0))
        x0, y0, x1, y1 = self.card_box()
        r = self.px(RADIUS)
        sh = Image.new("L", self.size, 0)
        ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + self.px(6), x1, y1 + self.px(6)), r, fill=130)
        self._fill(img, sh.filter(ImageFilter.GaussianBlur(self.px(13))), (0, 0, 0))
        outer = self._aa(lambda d, k: d.rounded_rectangle((x0 * k, y0 * k, x1 * k - 1, y1 * k - 1), r * k, fill=255))
        self._fill(img, outer, CARD, 244)
        # amber glow behind the status dot, clipped to the card
        cx, cy = x0 + self.px(PAD + 5), y0 + self.px(PAD + 10)
        glow = Image.new("L", self.size, 0)
        gr = self.px(70)
        ImageDraw.Draw(glow).ellipse((cx - gr, cy - gr, cx + gr, cy + gr), fill=40)
        self._fill(img, ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(self.px(34))), outer), AMBER)
        t = max(1, self.px(1))
        inner = self._aa(lambda d, k: d.rounded_rectangle(
            ((x0 + t) * k, (y0 + t) * k, (x1 - t) * k - 1, (y1 - t) * k - 1), (r - t) * k, fill=255))
        self.border = ImageChops.subtract(outer, inner)
        self._fill(img, self.border, (255, 255, 255), 30)
        self.outer = outer
        # status dot
        dot = self.px(5)
        self._fill(img, self._aa(lambda d, k: d.ellipse(
            ((cx - dot - 3) * k, (cy - dot - 3) * k, (cx + dot + 3) * k, (cy + dot + 3) * k), fill=255)), AMBER, 60)
        self._fill(img, self._aa(lambda d, k: d.ellipse(
            ((cx - dot) * k, (cy - dot) * k, (cx + dot) * k, (cy + dot) * k), fill=255)), AMBER)
        d = ImageDraw.Draw(img)
        d.text((cx + self.px(16), cy), TITLE, font=self.f_title, fill=TEXT, anchor="lm")
        d.text((x0 + self.px(PAD), y0 + self.px(PAD + 30)), BODY, font=self.f_body, fill=SUB, anchor="lt")
        return img

    def frame(self, left_secs, progress, hover):
        """progress: 0..1 of the countdown elapsed."""
        img = self._base.copy()
        x0, y0, x1, y1 = self.card_box()
        d = ImageDraw.Draw(img)
        cy = y0 + self.px(PAD + 10)
        d.text((x1 - self.px(PAD), cy), f"en {max(0, math.ceil(left_secs))} s", font=self.f_time,
               fill=DIM, anchor="rm")
        # buttons
        for name, (bx0, by0, bx1, by1) in self.buttons().items():
            hov = hover == name
            r = (by1 - by0) / 2
            mask = self._aa(lambda dd, k, b=(bx0, by0, bx1, by1): dd.rounded_rectangle(
                (b[0] * k, b[1] * k, b[2] * k, b[3] * k), r * k, fill=255))
            if name == "allow":
                self._fill(img, mask, tuple(min(255, c + 22) for c in BLUE) if hov else BLUE)
                fg = (255, 255, 255)
            else:
                self._fill(img, mask, (255, 255, 255), 26 if hov else 12)
                t = max(1, self.px(1))
                inner = self._aa(lambda dd, k, b=(bx0, by0, bx1, by1): dd.rounded_rectangle(
                    ((b[0] + t) * k, (b[1] + t) * k, (b[2] - t) * k, (b[3] - t) * k), (r - t) * k, fill=255))
                self._fill(img, ImageChops.subtract(mask, inner), (255, 255, 255), 40)
                fg = TEXT
            d = ImageDraw.Draw(img)
            d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), ALLOW if name == "allow" else DENY,
                   font=self.f_btn, fill=fg, anchor="mm")
        # countdown bar along the bottom edge, clipped to the rounded card
        bar_h = self.px(3)
        remaining = max(0.0, 1 - progress)
        if remaining > 0:
            bar = Image.new("L", self.size, 0)
            ImageDraw.Draw(bar).rectangle((x0, y1 - bar_h, x0 + int((x1 - x0) * remaining), y1), fill=255)
            self._fill(img, ImageChops.multiply(bar, self.outer), AMBER, 230)
        return img


# ----------------------------------------------------------------- Win32

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
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetCursor.argtypes = [wintypes.HANDLE]
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

WM_SETCURSOR, WM_MOUSEACTIVATE, WM_LBUTTONUP = 0x0020, 0x0021, 0x0202
MA_NOACTIVATE = 3
IDC_ARROW, IDC_HAND = 32512, 32649
# LAYERED | TOOLWINDOW | TOPMOST | NOACTIVATE  (not TRANSPARENT: the buttons must get clicks)
WS_EX = 0x00080000 | 0x00000080 | 0x00000008 | 0x08000000
WS_POPUP = 0x80000000


def _bgra(img):
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (r, g, b, a)).tobytes("raw", "BGRA")


def show(seconds: int) -> str:
    try:
        user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4))
    except Exception:
        pass
    scale = user32.GetDpiForSystem() / 96
    painter = Painter(scale)
    hits = painter.buttons()
    state = {"answer": None, "hover": None}

    def hit(x, y):
        for name, (x0, y0, x1, y1) in hits.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def proc(hwnd, msg, wparam, lparam):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE  # click without stealing keyboard focus
        if msg == WM_SETCURSOR:
            user32.SetCursor(user32.LoadCursorW(None, IDC_HAND if state["hover"] else IDC_ARROW))
            return 1
        if msg == WM_LBUTTONUP:
            x, y = ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value
            name = hit(x, y)
            if name:
                state["answer"] = name
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(proc)
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=wndproc, hInstance=hinst,
                     lpszClassName="ClaudeConsentPrompt")
    user32.RegisterClassExW(ctypes.byref(wc))
    w, h = painter.size
    work = wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)
    x = work.left + (work.right - work.left - w) // 2
    y_final = work.top + painter.px(18)
    hwnd = user32.CreateWindowExW(WS_EX, "ClaudeConsentPrompt", "Claude", WS_POPUP, x, y_final, w, h,
                                  None, None, hinst, None)
    user32.SetWindowDisplayAffinity(hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE, like the control indicator

    def present(img, y, alpha):
        bmi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                               biPlanes=1, biBitCount=32, biCompression=0)
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits, _bgra(img), w * h * 4)
        old = gdi32.SelectObject(mem, hbmp)
        blend = BLENDFUNCTION(0, 0, max(0, min(255, int(alpha * 255))), 1)
        user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(wintypes.POINT(x, y)), ctypes.byref(wintypes.SIZE(w, h)),
                                   mem, ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)

    start = time.monotonic()
    shown = False
    msg = wintypes.MSG()
    answer = "timeout"
    try:
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if state["answer"]:
                answer = state["answer"]
                break
            elapsed = time.monotonic() - start
            if elapsed >= seconds:
                break
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            state["hover"] = hit(pt.x - x, pt.y - y_final)
            appear = ease_out(min(1.0, elapsed / 0.3))
            present(painter.frame(seconds - elapsed, elapsed / seconds, state["hover"]),
                    y_final - int((1 - appear) * painter.px(14)), appear)
            if not shown:
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                shown = True
            time.sleep(1 / 40)
        # quick fade out
        t0 = time.monotonic()
        last = painter.frame(max(0.0, seconds - (t0 - start)), min(1.0, (t0 - start) / seconds), None)
        while (p := (time.monotonic() - t0) / 0.18) < 1:
            present(last, y_final, 1 - p)
            time.sleep(1 / 60)
    finally:
        user32.DestroyWindow(hwnd)
    return answer


def preview(path):
    p = Painter(1.0)
    frames = [p.frame(7, 0.0, None), p.frame(4.2, 0.4, "allow"), p.frame(1.1, 0.85, "deny")]
    sheet = Image.new("RGBA", (p.size[0], p.size[1] * 3), (58, 66, 92, 255))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f, (0, i * p.size[1]))
    sheet.convert("RGB").save(path)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    else:
        sys.stderr.write(show(int(sys.argv[1]) if len(sys.argv) > 1 else 7) + "\n")  # stdout is MCP's
