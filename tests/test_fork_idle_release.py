"""Fork (Maxi-Andres/Windows-MCP): AI control is handed back after idle seconds with no call."""

import time

from windows_mcp.desktop.control import ControlCoordinator


def _owner(idle):
    owner = ControlCoordinator()
    owner._state = "ready"
    owner.call_lease_timeout_seconds = 0  # isolate from the stalled-call lease
    owner.idle_release_seconds = idle
    return owner


def test_idle_release_hands_back_control_and_keeps_consent():
    owner = _owner(0.05)
    owner._consented = True
    try:
        owner.end_call(owner.begin_call("Click"))
        assert owner.status()["state"] == "ai"
        time.sleep(0.08)
        assert owner.status()["state"] == "ready"
        assert owner._suppress is False
        assert owner._consented is True  # no new countdown prompt next time
    finally:
        owner.stop()


def test_idle_release_waits_while_a_call_is_running():
    owner = _owner(0.05)
    try:
        token = owner.begin_call("Click")
        time.sleep(0.08)
        assert owner.status()["state"] == "ai"  # a running call is not idle
        owner.end_call(token)
        time.sleep(0.08)
        assert owner.status()["state"] == "ready"
    finally:
        owner.stop()


def test_idle_release_off_by_default():
    owner = ControlCoordinator()
    owner._state = "ready"
    owner.call_lease_timeout_seconds = 0
    try:
        assert owner.idle_release_seconds == 0
        owner.end_call(owner.begin_call("Click"))
        time.sleep(0.08)
        assert owner.status()["state"] == "ai"
    finally:
        owner.stop()
