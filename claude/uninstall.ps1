# Removes everything install.ps1 set up: MCP registration, permissions, hook, HUD files and the uv tool.
#
#   powershell -ExecutionPolicy Bypass -File .\uninstall.ps1

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$cfgPath = Join-Path $root 'config\settings.json'
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$claudeDir = Join-Path $HOME '.claude'
$settings = Join-Path $claudeDir 'settings.json'

Write-Host '==> Removing MCP server registration'
cmd /c "claude mcp remove --scope user $($cfg.mcp.name) 2>&1"

Write-Host '==> Removing permissions and hook from settings.json'
if (Test-Path $settings) {
    Copy-Item $settings "$settings.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { $py = "$(uv python find 3.13)".Trim() }
    & $py (Join-Path $root 'scripts\merge_settings.py') $settings $cfgPath --remove
}

Write-Host '==> Removing the HUD'
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*windows-hud*hud.pyw*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Recurse -Force (Join-Path $claudeDir 'hooks\windows-hud') -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'claude-hud') -ErrorAction SilentlyContinue

Write-Host '==> Uninstalling windows-mcp'
cmd /c "uv tool uninstall $($cfg.mcp.package) 2>&1"

Write-Host 'Done. Restart Claude Code.'
