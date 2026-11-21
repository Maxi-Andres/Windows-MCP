"""Live preview of the HUD on screen: plays a scripted sequence of fake actions.

Nothing is actually clicked or typed; it only feeds the panel so you can see every
state (looking, acting, important action, idle, compact, hidden) in ~40 seconds.
Uses its own log folder, so the real history is not touched. The real HUD is stopped
during the demo and comes back by itself on Claude's next action.

    <windows-mcp python> demo.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

HERE = Path(__file__).resolve().parent
DEMO_DIR = Path(tempfile.gettempdir()) / "claude-hud-demo"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")

# (seconds to show it, icon type, kind, text, narration)
STEPS = [
    (3.5, "look", "look", "Mirando la pantalla", "Primero miro la pantalla (naranja)"),
    (3.0, "app", "act", "Abriendo Bloc de notas", "Abro una app (azul)"),
    (2.5, "click", "act", "Click en (1280, 720)", "Hago click"),
    (3.0, "type", "act", "Escribiendo «Hola Max, esto es una prueba del panel» + Enter", "Escribo texto"),
    (2.5, "key", "act", "Atajo de teclado: ctrl+s", "Uso un atajo"),
    (3.0, "look", "look", "Leyendo botones y textos + captura", "Vuelvo a mirar"),
    (2.5, "scroll", "act", "Scroll hacia abajo ×3 en (1280, 900)", "Scroll"),
    (3.5, "kill", "danger", "Cerrando el proceso notepad.exe", "Acción importante (rojo)"),
    (2.0, "wait", "info", "Esperando 2 s", "Espero"),
]
TIMINGS = {"CLAUDE_HUD_ACTIVE_SECS": "3", "CLAUDE_HUD_COMPACT_SECS": "9",
           "CLAUDE_HUD_HIDE_SECS": "16", "CLAUDE_HUD_EXIT_SECS": "20"}


def stop_huds():
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
            if any(c.endswith("hud.pyw") for c in cmd) and "--preview" not in cmd:
                p.kill()
        except (psutil.Error, TypeError):
            continue
    time.sleep(0.3)


def say(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def main():
    stop_huds()
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    log = DEMO_DIR / "actions.jsonl"
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "CLAUDE_HUD_DIR": str(DEMO_DIR), **TIMINGS}
    hud = subprocess.Popen([str(PYTHONW), str(HERE / "hud.pyw")], env=env)

    for secs, type_, kind, text, narration in STEPS:
        say(narration)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "type": type_, "text": text, "kind": kind},
                               ensure_ascii=False) + "\n")
        time.sleep(secs)

    say("Termino: queda en gris con 'hace X s'")
    time.sleep(7)
    say("Se achica a una pastilla")
    time.sleep(7)
    say("Y se oculta solo")
    try:
        hud.wait(timeout=10)
    except subprocess.TimeoutExpired:
        hud.kill()
    say("Fin de la demo")


if __name__ == "__main__":
    main()
