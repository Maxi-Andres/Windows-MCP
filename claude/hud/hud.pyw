"""Always-on-top HUD that shows what Claude is doing on the desktop.

Fed by hook.py through %LOCALAPPDATA%\\claude-hud\\actions.jsonl. Click-through,
never takes focus, and is excluded from screen captures so it does not get in
the way of Claude's own screenshots. Hides after a while without actions and
exits after 15 minutes idle (the hook relaunches it on the next action).
"""

import ctypes
import json
import os
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32

_mutex = k32.CreateMutexW(None, False, "Local\\ClaudeWindowsHUD")
if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS: another HUD is running
    sys.exit(0)

DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "claude-hud"
LOG = DIR / "actions.jsonl"
BEAT = DIR / "heartbeat"

ACTIVE_SECS = 4  # header says "mirando/usando" for this long after an action
COMPACT_SECS = 30  # then collapse to the last action only
HIDE_SECS = 120  # then hide
EXIT_SECS = 900  # then quit
ROWS = 5

BG = "#15171c"
FG = "#e8eaed"
DIM = "#7d8590"
COLORS = {"look": "#f5a524", "act": "#4ea1ff", "danger": "#ff5c5c", "info": "#b0b8c4"}


def read_events(n=ROWS):
    try:
        with LOG.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines[-n:]:
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events


def work_area():
    r = wintypes.RECT()
    u32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA (primary)
    return r


def ago(secs):
    secs = int(secs)
    if secs < 60:
        return f"{secs} s"
    return f"{secs // 60} min"


class HUD:
    def __init__(self):
        self.root = root = tk.Tk()
        root.title("Claude HUD")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.93)
        self.scale = root.winfo_fpixels("1i") / 96
        wrap = int(430 * self.scale)

        self.border = tk.Frame(root, bg=COLORS["info"])
        self.border.pack(fill="both", expand=True)
        body = tk.Frame(self.border, bg=BG, padx=12, pady=8)
        body.pack(fill="both", expand=True, padx=2, pady=2)
        self.header = tk.Label(body, bg=BG, fg=FG, anchor="w", font=("Segoe UI Semibold", 10))
        self.header.pack(fill="x")
        self.rows = []
        for _ in range(ROWS):
            lbl = tk.Label(body, bg=BG, fg=DIM, anchor="w", justify="left",
                           wraplength=wrap, font=("Segoe UI Symbol", 9))
            self.rows.append(lbl)

        root.update_idletasks()
        self.hwnd = u32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        style = u32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW (no taskbar) | NOACTIVATE
        style |= 0x00080000 | 0x00000020 | 0x00000080 | 0x08000000
        u32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
        if not os.environ.get("CLAUDE_HUD_VISIBLE_IN_CAPTURE"):
            u32.SetWindowDisplayAffinity(self.hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE

        self.stat = None
        self.events = []
        self.signature = None
        self.hidden = False
        self.last_beat = 0
        self.root.after(0, self.tick)

    def place(self):
        self.root.update_idletasks()
        r = work_area()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        margin = int(16 * self.scale)
        self.root.geometry(f"+{r.right - w - margin}+{r.bottom - h - margin}")

    def render(self, idle):
        newest = self.events[-1]
        active = idle < ACTIVE_SECS
        if active and newest["kind"] == "look":
            head, color = "◉  Claude está mirando tu pantalla", COLORS["look"]
        elif active:
            head, color = "●  Claude está usando tu PC", COLORS[newest["kind"]]
        else:
            head, color = f"○  Claude · última acción hace {ago(idle)}", DIM
        shown = self.events if idle < COMPACT_SECS else self.events[-1:]
        sig = (head, color, tuple(e["t"] for e in shown))
        if sig == self.signature:
            return
        self.signature = sig
        self.border.configure(bg=color)
        self.header.configure(text=head, fg=color if active else FG)
        for lbl in self.rows:
            lbl.pack_forget()
        start = ROWS - len(shown)
        for idx, ev in enumerate(shown):
            lbl = self.rows[start + idx]
            stamp = time.strftime("%H:%M:%S", time.localtime(ev["t"]))
            is_newest = ev is newest
            lbl.configure(text=f"{stamp}   {ev['icon']}  {ev['text']}",
                          fg=COLORS.get(ev["kind"], FG) if is_newest else DIM)
        # newest at the bottom, like a chat
        for ev_idx in range(len(shown)):
            self.rows[start + ev_idx].pack(fill="x", pady=(2, 0))
        self.place()

    def tick(self):
        now = time.time()
        if now - self.last_beat > 1:
            try:
                DIR.mkdir(parents=True, exist_ok=True)
                BEAT.write_text(str(now))
            except OSError:
                pass
            self.last_beat = now
        try:
            st = LOG.stat()
            stat = (st.st_mtime_ns, st.st_size)
        except OSError:
            stat = None
        if stat != self.stat:
            self.stat = stat
            self.events = read_events()
        idle = now - self.events[-1]["t"] if self.events else EXIT_SECS + 1
        if idle > EXIT_SECS:
            self.root.destroy()
            return
        if idle > HIDE_SECS:
            if not self.hidden:
                self.root.withdraw()
                self.hidden = True
                self.signature = None
        else:
            if self.hidden:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.hidden = False
            self.render(idle)
        self.root.after(150, self.tick)


if __name__ == "__main__":
    HUD().root.mainloop()
