"""Fork (Maxi-Andres/Windows-MCP): capture flash draws one edge per monitor."""

import importlib
from types import SimpleNamespace as R

import pytest

import windows_mcp.uia as uia
from windows_mcp.desktop import flash_overlay

PRIMARY = R(left=0, top=0, right=2560, bottom=1440)
LEFT = R(left=-1920, top=0, right=0, bottom=1080)
BOTH = R(left=-1920, top=0, right=2560, bottom=1440)  # bounding box upstream passes


@pytest.fixture
def claude_flash(monkeypatch):
    monkeypatch.setenv("WINDOWS_MCP_OVERLAY_STYLE", "claude")
    module = importlib.reload(flash_overlay)
    calls = []
    monkeypatch.setattr(module, "_upstream_show_capture_flash", calls.append)
    monkeypatch.setattr(uia, "GetMonitorsRect", lambda: [PRIMARY, LEFT])
    yield module, calls
    monkeypatch.delenv("WINDOWS_MCP_OVERLAY_STYLE")
    importlib.reload(flash_overlay)


def test_all_monitors_become_one_edge_per_monitor(claude_flash):
    module, calls = claude_flash
    module.show_capture_flash(BOTH)
    assert calls == [None]  # upstream's per-monitor path


def test_single_monitor_and_regions_pass_through(claude_flash):
    module, calls = claude_flash
    region = R(left=100, top=100, right=500, bottom=400)
    module.show_capture_flash(PRIMARY)
    module.show_capture_flash(region)
    assert calls == [PRIMARY, region]


def test_inset_is_flush_with_the_screen_edge(claude_flash):
    module, _ = claude_flash
    assert module._FULLSCREEN_INSET == 0
