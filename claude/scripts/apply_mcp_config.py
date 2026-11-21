"""Apply our Windows-MCP settings to ~/.windows-mcp/config.toml.

Uses Windows-MCP's own load_config/write_config, so validation and format match the
server and any other setting already in the file is kept. Run it with the windows-mcp
tool's Python (install.ps1 does):

    python apply_mcp_config.py <claude/config/settings.json>

Reads the "windows_mcp" object, e.g. {"control": {"consent_countdown_seconds": 5}}.
"""

import json
import sys
from pathlib import Path

from windows_mcp.infrastructure.config import CONFIG_FILE, load_config, write_config


def main():
    ours = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")).get("windows_mcp", {})
    cfg = load_config(CONFIG_FILE if CONFIG_FILE.exists() else None)
    for section, values in ours.items():
        target = getattr(cfg, section)
        for key, value in values.items():
            if not hasattr(target, key):
                raise SystemExit(f"Unknown Windows-MCP setting: {section}.{key}")
            setattr(target, key, value)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_config(cfg, CONFIG_FILE)
    load_config(CONFIG_FILE)  # re-read: fails loudly if a value is out of range
    sys.stderr.write(f"Updated {CONFIG_FILE}\n")


if __name__ == "__main__":
    main()
