# Notas de Claude: nuestra capa sobre Windows-MCP

Este repo es la copia de Max (`Maxi-Andres/Windows-MCP`, público) de
[CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP). Le da a Claude Code
control del escritorio de Windows (servidor MCP `windows`, herramientas `mcp__windows__*`) y
le muestra a Max en pantalla todo lo que Claude hace. **Todo lo nuestro vive en `claude/`**;
el resto es código de ellos sin tocar, para poder traer sus versiones sin conflictos. Únicas
excepciones (revisarlas si un merge de upstream choca):
- la línea `@claude/CLAUDE.md` al principio del `CLAUDE.md` de la raíz;
- `src/windows_mcp/desktop/claude_overlay_art.py` (archivo nuevo, nuestro) y las 3 líneas al final de
  `src/windows_mcp/desktop/control_overlay_art.py` que lo cargan si `WINDOWS_MCP_OVERLAY_STYLE=claude`;
- `src/windows_mcp/desktop/claude_consent.py` (nuevo, nuestro) y el bloque `__main__` de
  `src/windows_mcp/desktop/control_consent.py`, que lo usa con la misma variable;
- `src/windows_mcp/desktop/control.py`: 3 bloques marcados `Fork` para la liberación automática
  (`WINDOWS_MCP_IDLE_RELEASE_SECONDS`), con su test en `tests/test_fork_idle_release.py` (archivo nuevo).

Objetivo de Max: que Claude haga las cosas en la PC en vez de pedirle que las haga él, pero
viendo siempre qué hace (aunque no pida permiso).

## Estructura de `claude/`

| Archivo | Qué es |
|---|---|
| `install.ps1` | Deja una PC lista: instala Windows-MCP **desde este clon**, lo registra en Claude Code, copia el HUD a `~/.claude/hooks/windows-hud/` y mergea permisos + hook en `~/.claude/settings.json` (backup antes). Idempotente. |
| `update.ps1` | Trae el último tag `vX.Y.Z` de upstream, muestra el diff de `src/`, pregunta, mergea y reinstala. |
| `uninstall.ps1` | Saca todo lo anterior. |
| `config/settings.json` | Nombre del servidor, herramientas excluidas, env, lista de permisos y config del hook. Fuente de verdad de la config. |
| `scripts/merge_settings.py` | Mergea/saca nuestra parte de `settings.json` sin tocar lo demás (escribe LF, sin duplicar). |
| `hud/hook.py` | Hook PreToolUse (`mcp__windows__.*`): traduce cada acción a una frase en castellano y la agrega a `actions.jsonl`; lanza el HUD si no está vivo. Nunca bloquea (siempre exit 0). |
| `hud/hud.pyw` | El panel: ventana Win32 layered con alpha por píxel, dibujada con Pillow. `--preview out.png` renderiza todos los estados a una imagen. |
| `hud/demo.py` | Demo en vivo (~40 s) con acciones falsas que recorre todos los estados. |

## Decisiones tomadas (y por qué)

- **Telemetría apagada** (`ANONYMIZED_TELEMETRY=false`): sin eso manda nombres de herramientas y textos de errores (pueden tener rutas). Verificado en el código que con `false` no se crea el cliente PostHog.
- **Excluidas `PowerShell`, `FileSystem`, `Registry`**: Claude ya tiene sus propias herramientas para consola/archivos, y Registry es riesgosa. Elegido por Max.
- **Permisos**: todo pasa sin preguntar salvo `Clipboard` (puede leer contraseñas copiadas). Elegido por Max.
- **Solo tags de upstream**, no su `main`. El tag v0.8.9 se verificó idéntico al paquete de PyPI que se auditó (Defender limpio, sin código ofuscado, red solo PostHog + Scrape). **Antes de aceptar una versión nueva, revisar el diff de `src/` buscando red, ejecución de código, persistencia.**
- **Remotos**: `origin` = Max, `upstream` = CursorTouch con push deshabilitado. GitHub Actions apagado en el repo de Max (sus workflows publican en PyPI).
- **Aviso de control de Windows-MCP rediseñado** (a Max el original le pareció horrible: borde azul de 56 px, velo, cartel "AI is controlling this computer"). Con `WINDOWS_MCP_OVERLAY_STYLE=claude` (en `config/settings.json`) se usa `claude_overlay_art.py`: borde de 2 px, pastilla oscura en castellano arriba al centro ("Claude está usando tu PC · Mové el mouse o apretá Ctrl+Alt+Shift+Backspace para frenarlo"), anillo fino con etiqueta "Claude" en el cursor y ripple fino al hacer click. La lógica de control/takeover de ellos no cambia. Sin la variable se ve como upstream.
  - Con el estilo activado fallan 7 tests de `tests/test_control_overlay_visuals.py`: verifican el aspecto de upstream (texto en inglés, forma del brillo). Esperado. Sin la variable pasan todos.
  - Vista previa sin reiniciar nada: componer los bitmaps de ambos módulos sobre una captura (`PIL.ImageGrab`), porque el overlay real está excluido de las capturas.
- **Aviso de consentimiento rediseñado** (el "AI is about to take control" con cuenta regresiva, tkinter gris): con el mismo estilo `claude` sale una tarjeta oscura arriba al centro, en castellano, con "No, ahora no" / "Dejar ahora" y una barra ámbar que se achica. Mismo contrato que el original (`allow`/`deny`/`timeout`, códigos 10/11/12), no toma foco (`WM_MOUSEACTIVATE` → `MA_NOACTIVATE`). Se ejecuta en un proceso aparte con `python -I`, por eso carga `claude_consent.py` por ruta y no importa el paquete. Aparece al empezar cada período de control (también después de que Max me frena). Duración: `control.consent_countdown_seconds` en `~/.windows-mcp/config.toml` (default 10, 0 = sin aviso).
  - Probar en vivo: `$env:WINDOWS_MCP_OVERLAY_STYLE='claude'; & $py -I <site-packages>\windows_mcp\desktop\control_consent.py 7` (exit 10/11/12). Vista previa: `& $py -I ...\claude_consent.py --preview out.png`.
  - Nada en el paquete puede escribir a stdout (`tests/test_no_stdout_writes.py`): stdout es el canal MCP.
- **Destello de captura apagado** (`WINDOWS_MCP_DISABLE_FLASH=1`): el HUD ya muestra "mirando tu pantalla".
- Cambios de `env` o de `src/` recién se ven cuando se reinicia el servidor: `/mcp` → windows → Reconnect, o reiniciar Claude Code.
- **El HUD y el hook corren con el Python del venv de la herramienta** (`<uv tool dir>\windows-mcp\Scripts\python.exe`): ya trae Pillow, numpy y psutil, no hay que instalar nada más.

## HUD: cómo funciona

- Log: `%LOCALAPPDATA%\claude-hud\actions.jsonl` (o `$CLAUDE_HUD_DIR`). Línea: `{"t", "type", "text", "kind"}`; `type` elige el ícono (Segoe Fluent Icons), `kind` el color: `look` naranja, `act` azul, `danger` rojo, `info` gris.
- Estados: tarjeta completa (acción actual + 4 anteriores) → pastilla compacta a los 30 s → oculto a los 120 s → el proceso termina a los 900 s (el hook lo relanza). Tiempos configurables con `CLAUDE_HUD_ACTIVE_SECS`, `_COMPACT_SECS`, `_HIDE_SECS`, `_EXIT_SECS`.
- Atraviesa clics, no toma foco, abajo a la derecha del monitor principal, **excluido de capturas** (`WDA_EXCLUDEFROMCAPTURE`); `CLAUDE_HUD_VISIBLE_IN_CAPTURE=1` lo desactiva para probar.
- Instancia única por mutex `Local\ClaudeWindowsHUD`. Ver 2 procesos `pythonw` es normal: el `pythonw.exe` del venv es un lanzador que arranca el intérprete real como hijo.
- Probar diseño: `python hud\hud.pyw --preview out.png` (rápido, sin ventana). Probar en vivo: `python hud\demo.py`.

## Trampas conocidas

- **Mientras la IA tiene el control, el gancho de teclado de Windows-MCP descarta las teclas físicas de Max** (`control_hooks.physical_key` devuelve 1). Apretar teclas no le devuelve el control; solo mover bastante el mouse o `Ctrl+Alt+Shift+Backspace`. En upstream el control no vence solo. Por eso: (1) regla de liberar siempre al terminar, y (2) nuestro `WINDOWS_MCP_IDLE_RELEASE_SECONDS=20` lo libera a los 20 s sin acciones (pasa a `ready` sin perder el consentimiento, así que no vuelve a salir la cuenta regresiva).
- **Al reconectar con `/mcp`, el servidor viejo puede quedar vivo** (pasó el 2026-11-21: PID del 11:26 siguió corriendo con sus ganchos después de reconectar a las 11:49). Si algo raro pasa con el teclado/mouse, buscar procesos `windows-mcp.exe` de más con su padre (`psutil`) y cerrar los huérfanos.
- Config del servidor (`~/.windows-mcp/config.toml`): la escribe `scripts/apply_mcp_config.py` desde la clave `windows_mcp` de `config/settings.json` (hoy: cuenta regresiva de 5 s). Usa `load_config`/`write_config` de ellos. Se aplica al reiniciar el servidor.

- **No usar `uv tool install --force` con Claude Code abierto**: borra la carpeta de la herramienta, falla a mitad (archivos en uso por el servidor) y la deja rota. `install.ps1` por eso actualiza en el lugar con `uv pip install --reinstall-package` si ya existe.
- El HUD **no aparece en el Screenshot de Windows-MCP (dxcam)** aunque esté visible para Max. Para verlo, usar `--preview` o una captura GDI (`Graphics.CopyFromScreen`) con `CLAUDE_HUD_VISIBLE_IN_CAPTURE=1`.
- Pillow `ImageDraw` sobre RGBA **reemplaza** píxeles en vez de mezclar: usar colores opacos o capas + `alpha_composite`.
- El hook lee stdin como bytes `utf-8-sig` (Windows decodifica cp1252 y PowerShell agrega BOM).
- Un panel viejo corriendo bloquea al nuevo por el mutex: matar procesos `hud.pyw` después de cambiar el HUD.

## Usar el escritorio de Max (aprendido en uso)

- Windows en **castellano**: apps por nombre del menú Inicio en castellano ("Bloc de notas", no "Notepad").
- En el Bloc de notas en castellano **`Ctrl+A` es Abrir**, no seleccionar todo. Regla general (también en `~/.claude/CLAUDE.md`): antes de un atajo dentro de una app, ver el idioma y leer el atajo real en el menú de la app; si no hay, click en la opción del menú. Para vaciar un campo usar `Type` con `clear=true` y texto vacío.
- Dos monitores: principal 2560×1440 en (0,0) y secundario 1920×1080 a la izquierda en (-1920,0). Las apps pueden abrirse en el secundario: revisar con `Snapshot` `display=[1]`.
- Si Max mueve el mouse, Windows-MCP devuelve error `USER_CONTROL`: esperar unos segundos y reintentar.
- No abrir ni leer archivos que no hagan falta para la tarea.

## Convenciones

- Commits: solo cuando Max lo pide en la sesión, mensajes simples, **sin `Co-Authored-By` ni atribución**.
- Después de cambiar algo en `claude/`, correr `claude\install.ps1` para aplicarlo en esta PC.

## Estado

- 2026-11-21: HUD rediseñado (Pillow + ventana layered) para reemplazar la versión tkinter que a Max le pareció fea; mostrado con la demo y acciones reales. Aviso de control de Windows-MCP rediseñado con el mismo estilo. Esperando su opinión sobre ambos. Cambios sin commitear hasta que Max lo pida.
