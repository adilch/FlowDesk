"""M0 spike: WSL bridge echo test + path translation (pure-Python parts always run)."""

from __future__ import annotations

import sys
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from flowdesk.platform import wsl

pytestmark_windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


# --- Path translation: pure logic, runs everywhere --------------------------------


def test_windows_drive_to_wsl() -> None:
    p = wsl.windows_to_wsl_path(PureWindowsPath(r"C:\Users\adil\case"), "Ubuntu-24.04")
    assert p == PurePosixPath("/mnt/c/Users/adil/case")


def test_wsl_unc_to_linux_path() -> None:
    p = wsl.windows_to_wsl_path(
        PureWindowsPath(r"\\wsl$\Ubuntu-24.04\home\adil\flowdesk\case"), "Ubuntu-24.04"
    )
    assert p == PurePosixPath("/home/adil/flowdesk/case")


def test_wsl_home_to_unc() -> None:
    p = wsl.wsl_to_windows_path(PurePosixPath("/home/adil/flowdesk"), "Ubuntu-24.04")
    assert str(p) == r"\\wsl$\Ubuntu-24.04\home\adil\flowdesk"


def test_wsl_mnt_back_to_drive() -> None:
    p = wsl.wsl_to_windows_path(PurePosixPath("/mnt/c/Users/adil"), "Ubuntu-24.04")
    assert str(p) == r"C:\Users\adil"


def test_roundtrip_translation() -> None:
    original = PureWindowsPath(r"C:\dev\FlowDesk\case")
    there = wsl.windows_to_wsl_path(original, "Ubuntu-24.04")
    back = wsl.wsl_to_windows_path(there, "Ubuntu-24.04")
    assert back == original


def test_shell_quote_embedded_quote() -> None:
    assert wsl.shell_quote("it's") == "'it'\\''s'"


# --- Live WSL tests: skip honestly when WSL absent ---------------------------------


def _wsl_available() -> bool:
    return sys.platform == "win32" and wsl.probe().installed and bool(wsl.probe().distros)


requires_wsl = pytest.mark.skipif(
    not _wsl_available(), reason="WSL2 with a distro is not installed on this machine"
)


@requires_wsl
def test_echo_through_bridge() -> None:
    """M0 gate component: a command crosses the bridge and comes back clean."""
    result = wsl.run("echo flowdesk-bridge-ok")
    assert result.returncode == 0
    assert result.stdout.strip() == "flowdesk-bridge-ok"


@requires_wsl
def test_exit_code_propagates() -> None:
    result = wsl.run("exit 3")
    assert result.returncode == 3
