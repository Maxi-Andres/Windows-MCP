# Windows-MCP + Claude Code (nuestra versión)

Copia de [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) con lo nuestro agregado.
Le da a Claude Code control del escritorio de Windows (ver la pantalla, mouse, teclado, abrir apps)
y te muestra en un panel en pantalla **todo lo que hace**, aunque no te pida permiso.

Todo lo nuestro vive en esta carpeta `claude/`; el resto del repo es el código de ellos sin cambios,
así podemos traer sus actualizaciones sin conflictos.

## Instalar en una PC nueva

Requisitos: Windows 10/11, [Claude Code](https://code.claude.com) y git. `uv` se instala solo con winget si falta.

```powershell
git clone https://github.com/Maxi-Andres/Windows-MCP.git C:\Users\$env:USERNAME\Code\personal\Windows-MCP
cd C:\Users\$env:USERNAME\Code\personal\Windows-MCP
powershell -ExecutionPolicy Bypass -File .\claude\install.ps1
```

Después reiniciá Claude Code. Se puede correr de nuevo cuantas veces quieras: actualiza todo en el lugar.

## Qué hace el instalador

1. Instala Windows-MCP **desde este repo** (`uv tool install`), así que cualquier cambio nuestro al código se aplica.
2. Lo registra en Claude Code como servidor `windows` (a nivel usuario), con la telemetría apagada
   y **sin** las herramientas `PowerShell`, `FileSystem` y `Registry` (Claude ya tiene las suyas, y Registry es riesgosa).
3. Copia el panel a `~/.claude/hooks/windows-hud/`.
4. Agrega a `~/.claude/settings.json` (con backup antes) los permisos y el hook del panel.

## Permisos

Pasan sin preguntar: `Screenshot`, `Snapshot`, `DisplayInventory`, `ControlStatus`, `Wait`, `WaitFor`,
`Click`, `Move`, `Scroll`, `Type`, `MultiEdit`, `MultiSelect`, `Shortcut`, `App`, `Process`, `Scrape`, `Notification`.

Pide permiso: `Clipboard` (puede leer contraseñas copiadas).

Se cambian en [`config/settings.json`](config/settings.json) y se aplican corriendo `install.ps1` de nuevo.

## El panel (HUD)

Antes de cada acción, un hook de Claude Code la anota en un panel abajo a la derecha del monitor principal:

- **Naranja** — "Claude está mirando tu pantalla" (capturas / leer la pantalla)
- **Azul** — "Claude está usando tu PC" (mouse, teclado, apps)
- **Rojo** — acciones peligrosas (cerrar un proceso)
- **Gris** — "última acción hace X". A los 30 s se achica, a los 2 min se oculta.

Los clics lo atraviesan, nunca roba el foco y **no sale en capturas** (ni en las de Claude ni en grabaciones).
Historial completo en `%LOCALAPPDATA%\claude-hud\actions.jsonl`.
Para probarlo y que sí salga en capturas: variable de entorno `CLAUDE_HUD_VISIBLE_IN_CAPTURE=1`.

Archivos: [`hud/hook.py`](hud/hook.py) (traduce cada acción a una frase) y [`hud/hud.pyw`](hud/hud.pyw) (el panel).

## Frenar a Claude

Mové el mouse o apretá `Ctrl+Alt+Shift+Backspace`: recuperás el control al instante (función de Windows-MCP).

## Traer actualizaciones de ellos

```powershell
powershell -ExecutionPolicy Bypass -File .\claude\update.ps1
git push
```

Busca la última versión publicada (tag `vX.Y.Z`) del repo original, te muestra qué archivos cambiaron
y, si confirmás, la mergea y reinstala. Solo toma versiones publicadas, no la rama `main` del día.
Conviene que Claude revise el diff antes de aceptar una versión nueva.

## Desinstalar

```powershell
powershell -ExecutionPolicy Bypass -File .\claude\uninstall.ps1
```

## Revisión de seguridad (v0.8.9, 2026-11-21)

- Windows Defender: sin amenazas.
- Código Python puro, sin binarios ni código ofuscado (`eval`/`exec`/base64).
- Red: solo telemetría PostHog (apagada con `ANONYMIZED_TELEMETRY=false`; se verificó en el código que así no se crea el cliente) y la herramienta `Scrape` cuando se usa.
- No se instala al inicio de Windows salvo que se corra `windows-mcp install`.
- El tag `v0.8.9` es idéntico al paquete publicado en PyPI.
