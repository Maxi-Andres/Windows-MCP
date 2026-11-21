# Brings in the latest Windows-MCP release from the original repo (CursorTouch) and reinstalls.
#
# Merges the newest release tag (vX.Y.Z), not upstream main, so we only take published versions.
# Our own files live in claude/, so merges normally have no conflicts.
#
#   powershell -ExecutionPolicy Bypass -File .\claude\update.ps1

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
function Git { git -C $repoRoot @args; if ($LASTEXITCODE -ne 0) { throw "git $args failed" } }

if (git -C $repoRoot status --porcelain) {
    Write-Host 'There are uncommitted changes. Commit or stash them first.' -ForegroundColor Red
    exit 1
}
if (-not (git -C $repoRoot remote | Select-String -SimpleMatch 'upstream')) {
    Git remote add upstream https://github.com/CursorTouch/Windows-MCP.git
}

Write-Host '==> Fetching releases from upstream (CursorTouch/Windows-MCP)'
Git fetch upstream --tags --quiet
$latest = git -C $repoRoot tag --list 'v*' --sort=-v:refname | Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } | Select-Object -First 1
$current = (git -C $repoRoot describe --tags --abbrev=0 --match 'v*').Trim()
Write-Host "Current: $current   Latest: $latest"

git -C $repoRoot merge-base --is-ancestor $latest HEAD
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Already up to date.' -ForegroundColor Green
    exit 0
}

Write-Host "`n==> Changes in their code from $current to ${latest}:"
git -C $repoRoot --no-pager diff --stat "$current" "$latest" -- src pyproject.toml

$answer = Read-Host "`nMerge $latest and reinstall? (s/n)"
if ($answer -notmatch '^[sSyY]') { Write-Host 'Cancelled, nothing changed.'; exit 0 }

git -C $repoRoot merge --no-edit $latest
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Merge has conflicts. Resolve them (or run: git merge --abort) and then run install.ps1.' -ForegroundColor Red
    exit 1
}

& (Join-Path $PSScriptRoot 'install.ps1')
Write-Host "`nUpdated to $latest. Remember to push: git push" -ForegroundColor Green
