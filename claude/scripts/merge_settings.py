"""Merge (or remove) this project's permissions and HUD hook in ~/.claude/settings.json.

Idempotent: running it again replaces the previous HUD hook entry instead of
duplicating it, and only adds allow rules that are missing. Everything else in
the settings file is left untouched.

    python merge_settings.py <settings.json> <config.json> --python <exe> --hook <hook.py>
    python merge_settings.py <settings.json> <config.json> --remove
"""

import argparse
import json
from pathlib import Path

HUD_MARKER = "windows-hud"


def is_ours(entry, matcher):
    return entry.get("matcher") == matcher and any(
        HUD_MARKER in h.get("command", "") for h in entry.get("hooks", [])
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("settings", type=Path)
    ap.add_argument("config", type=Path)
    ap.add_argument("--python")
    ap.add_argument("--hook")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()

    cfg = json.loads(a.config.read_text(encoding="utf-8-sig"))
    text = a.settings.read_text(encoding="utf-8-sig") if a.settings.exists() else ""
    data = json.loads(text) if text.strip() else {}

    rules = cfg["permissions"]["allow"]
    event, matcher = cfg["hook"]["event"], cfg["hook"]["matcher"]

    perms = data.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault(event, [])
    entries[:] = [e for e in entries if not is_ours(e, matcher)]

    if a.remove:
        allow[:] = [r for r in allow if r not in rules]
    else:
        if not (a.python and a.hook):
            ap.error("--python and --hook are required unless --remove")
        allow.extend(r for r in rules if r not in allow)
        py = a.python.replace("\\", "/")
        hook = a.hook.replace("\\", "/")
        entries.append({
            "matcher": matcher,
            "hooks": [{
                "type": "command",
                "command": f'"{py}" "{hook}"',
                "timeout": cfg["hook"]["timeout"],
            }],
        })

    # drop containers we may have emptied or created for nothing
    if not allow:
        perms.pop("allow")
    if not perms:
        data.pop("permissions")
    if not entries:
        hooks.pop(event)
    if not hooks:
        data.pop("hooks")

    a.settings.parent.mkdir(parents=True, exist_ok=True)
    a.settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(("Removed from " if a.remove else "Updated ") + str(a.settings))


if __name__ == "__main__":
    main()
