"""PreToolUse hook for mcp__windows__* tools.

Turns each desktop action Claude is about to take into a short Spanish line,
appends it to the HUD log and makes sure the on-screen HUD (hud.pyw) is running.
It never blocks or alters the tool call: any error is swallowed and it exits 0.

Each log line: {"t": epoch, "type": icon id, "text": "...", "kind": look|act|danger|info}
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DIR = Path(os.environ.get("CLAUDE_HUD_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "claude-hud")
LOG = DIR / "actions.jsonl"
BEAT = DIR / "heartbeat"
HUD = Path(__file__).with_name("hud.pyw")
PYTHONW = Path(sys.executable).with_name("pythonw.exe")


def short(value, n=70):
    s = " ".join(str(value).split()) if value is not None else ""
    return s if len(s) <= n else s[: n - 1] + "…"


def where(i):
    if i.get("label") is not None:
        return f" en el elemento #{i['label']}"
    loc = i.get("loc")
    if loc:
        if isinstance(loc, str):
            loc = loc.strip("[] ").replace(" ", "")
            return f" en ({loc.replace(',', ', ')})"
        return f" en ({', '.join(str(v) for v in loc)})"
    return ""


def truthy(v):
    return str(v).lower() == "true"


def describe(tool, i):
    """Return (type, text, kind). type picks the icon; kind picks the color."""
    if tool == "Screenshot":
        extra = " (una zona)" if i.get("region") else ""
        return "look", f"Mirando la pantalla{extra}", "look"
    if tool == "Snapshot":
        extra = " + captura" if truthy(i.get("use_vision")) else ""
        web = " de la página web" if truthy(i.get("use_dom")) else ""
        return "look", f"Leyendo botones y textos{web}{extra}", "look"
    if tool == "Click":
        button = i.get("button", "left")
        clicks = int(i.get("clicks", 1) or 1)
        name = {2: "Doble click", 3: "Triple click"}.get(clicks, "Click")
        if button == "right":
            name += " derecho"
        elif button == "middle":
            name += " del medio"
        return "click", name + where(i), "act"
    if tool == "Type":
        enter = " + Enter" if truthy(i.get("press_enter")) else ""
        if not i.get("text") and truthy(i.get("clear")):
            return "type", f"Borrando el texto{where(i)}", "act"
        clear = " (borrando antes)" if truthy(i.get("clear")) else ""
        return "type", f"Escribiendo «{short(i.get('text'), 50)}»{where(i)}{clear}{enter}", "act"
    if tool == "Scroll":
        d = {"up": "arriba", "down": "abajo", "left": "la izquierda", "right": "la derecha"}
        times = i.get("wheel_times", 1)
        return "scroll", f"Scroll hacia {d.get(i.get('direction', 'down'), '?')} ×{times}{where(i)}", "act"
    if tool == "Move":
        if truthy(i.get("drag")):
            src = i.get("from_loc")
            src = f" desde {short(src, 20)}" if src else ""
            return "move", f"Arrastrando{src} hasta{where(i)[3:] or ' ?'}", "act"
        return "move", f"Moviendo el mouse{where(i).replace(' en ', ' a ')}", "act"
    if tool == "Shortcut":
        return "key", f"Atajo de teclado: {short(i.get('shortcut'), 30)}", "act"
    if tool == "App":
        mode = i.get("mode", "launch")
        name = short(i.get("name") or i.get("executable") or "", 40)
        if mode == "launch":
            return "app", f"Abriendo {name}", "act"
        if mode == "launch_executable":
            return "app", f"Ejecutando {name}", "act"
        if mode == "switch":
            return "window", f"Cambiando a la ventana {name}", "act"
        return "window", f"Moviendo/redimensionando la ventana {name}", "act"
    if tool == "Process":
        if i.get("mode") == "kill":
            target = i.get("name") or f"PID {i.get('pid')}"
            return "kill", f"Cerrando el proceso {short(target, 40)}", "danger"
        return "list", "Viendo los programas abiertos", "info"
    if tool == "Clipboard":
        if i.get("mode") == "set":
            return "clipboard", f"Copiando al portapapeles «{short(i.get('text'), 40)}»", "act"
        return "clipboard", "Leyendo el portapapeles", "look"
    if tool == "Scrape":
        return "web", f"Leyendo la web {short(i.get('url'), 50)}", "info"
    if tool == "Notification":
        return "notify", f"Mostrándote una notificación: {short(i.get('title'), 40)}", "info"
    if tool == "Wait":
        return "wait", f"Esperando {i.get('duration')} s", "info"
    if tool == "WaitFor":
        what = i.get("text") or i.get("window_name") or i.get("condition")
        return "wait", f"Esperando a que aparezca {short(what, 40)}", "info"
    if tool == "MultiSelect":
        n = len(i.get("locs") or i.get("labels") or [])
        return "select", f"Seleccionando {n} elementos", "act"
    if tool == "MultiEdit":
        n = len(i.get("locs") or i.get("labels") or [])
        return "type", f"Completando {n} campos", "act"
    if tool == "DisplayInventory":
        return "display", "Viendo la info de los monitores", "info"
    if tool == "ControlStatus":
        if truthy(i.get("release")):
            return "info", "Devolviéndote el control", "info"
        return "info", "Chequeando quién tiene el control", "info"
    return "info", tool, "info"


def log_event(type_, text, kind):
    DIR.mkdir(parents=True, exist_ok=True)
    line = {"t": time.time(), "type": type_, "text": text, "kind": kind}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    if LOG.stat().st_size > 200_000:  # keep the log small
        lines = LOG.read_text(encoding="utf-8").splitlines()[-300:]
        LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_hud():
    try:
        if time.time() - BEAT.stat().st_mtime < 3:
            return
    except OSError:
        pass
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):  # try CREATE_BREAKAWAY_FROM_JOB first
        try:
            subprocess.Popen(
                [str(PYTHONW), str(HUD)],
                creationflags=flags | extra,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            return
        except OSError:
            continue


def main():
    # Raw bytes as UTF-8: Windows would otherwise decode stdin as cp1252, and a BOM
    # (PowerShell pipes add one) would break json parsing.
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    tool = payload.get("tool_name", "").split("__")[-1]
    log_event(*describe(tool, payload.get("tool_input") or {}))
    ensure_hud()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
