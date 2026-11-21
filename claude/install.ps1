# Sets up Windows desktop control for Claude Code on this PC:
#   1. installs Windows-MCP from THIS repo (our copy, including any changes we made) as a uv tool
#   2. registers it in Claude Code (user scope, telemetry off, risky tools excluded)
#   3. installs the HUD (hook + on-screen panel) in ~/.claude/hooks/windows-hud
#   4. merges the permissions and the hook into ~/.claude/settings.json (backup first)
# Safe to run again: it updates everything in place.
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$repoRoot = Split-Path $root -Parent
$cfgPath = Join-Path $root 'config\settings.json'
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mcp = $cfg.mcp

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

Step 'Checking requirements'
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Fail 'Claude Code (claude) is not installed or not in PATH. Install it first: https://code.claude.com'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv not found, installing it with winget...'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail 'Neither uv nor winget is available. Install uv: https://docs.astral.sh/uv/'
    }
    winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    Update-Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail 'uv was installed but is not in PATH yet. Open a new terminal and run this again.' }
}

$version = (git -C $repoRoot describe --tags 2>$null)
Step "Installing $($mcp.package) from $repoRoot ($version)"
uv tool install --force --reinstall-package $mcp.package --python $mcp.python $repoRoot
if ($LASTEXITCODE -ne 0) { Fail 'uv tool install failed' }
$binDir = (uv tool dir --bin).Trim()
$exe = Join-Path $binDir 'windows-mcp.exe'
if (-not (Test-Path $exe)) { Fail "windows-mcp.exe not found in $binDir" }

Step 'Finding a Python with tkinter for the HUD'
$py = (uv python find 3.13 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $py) {
    uv python install 3.13
    $py = (uv python find 3.13)
}
$py = "$py".Trim()
& $py -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) { Fail "Python at $py has no tkinter" }
if (-not (Test-Path (Join-Path (Split-Path $py) 'pythonw.exe'))) { Fail "pythonw.exe not found next to $py" }
Write-Host "Using $py"

Step 'Installing the HUD'
$claudeDir = Join-Path $HOME '.claude'
$hudDir = Join-Path $claudeDir 'hooks\windows-hud'
New-Item -ItemType Directory -Force $hudDir | Out-Null
# stop a running HUD so the new version is picked up on the next action
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*windows-hud*hud.pyw*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Copy-Item (Join-Path $root 'hud\*') $hudDir -Force
Write-Host "Copied to $hudDir"

Step "Registering MCP server '$($mcp.name)' in Claude Code"
$envArgs = @()
foreach ($p in $mcp.env.PSObject.Properties) { $envArgs += @('--env', "$($p.Name)=$($p.Value)") }
cmd /c "claude mcp remove --scope user $($mcp.name) >nul 2>&1"
claude mcp add --scope user --transport stdio $mcp.name @envArgs -- $exe serve --exclude-tools $mcp.exclude_tools
if ($LASTEXITCODE -ne 0) { Fail 'claude mcp add failed' }

Step 'Merging permissions and hook into settings.json'
$settings = Join-Path $claudeDir 'settings.json'
if (Test-Path $settings) {
    $backup = "$settings.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $settings $backup
    Write-Host "Backup: $backup"
}
& $py (Join-Path $root 'scripts\merge_settings.py') $settings $cfgPath --python $py --hook (Join-Path $hudDir 'hook.py')
if ($LASTEXITCODE -ne 0) { Fail 'Could not update settings.json' }

Step 'Done'
Write-Host 'Restart Claude Code (or reconnect the server in /mcp) so the tools load.'
Write-Host 'Stop Claude at any time by moving the mouse or pressing Ctrl+Alt+Shift+Backspace.'
