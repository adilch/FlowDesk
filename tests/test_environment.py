"""Environment probe, .wslconfig helper, ParaView detection (PRD §8)."""

from __future__ import annotations

import pytest

from flowdesk.platform import environment as env_probe
from flowdesk.platform.commands import probe_environment

_ENV = probe_environment()


def test_recommended_wslconfig_contents() -> None:
    text = env_probe.recommended_wslconfig(host_ram_mb=32_000)
    assert "[wsl2]" in text
    assert "memory=25GB" in text  # 80% of 32 GB
    assert "wsl --shutdown" in text  # honesty: restart requirement stated


def test_recommended_wslconfig_floor() -> None:
    assert "memory=4GB" in env_probe.recommended_wslconfig(host_ram_mb=2_000)


def test_read_wslconfig_limits(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / ".wslconfig"
    cfg.write_text("[wsl2]\nmemory=8GB\nprocessors=4\nswap=0\n")
    monkeypatch.setattr(env_probe, "wslconfig_path", lambda: cfg)
    limits = env_probe.read_wslconfig_limits()
    assert limits == {"memory": "8GB", "processors": "4"}


def test_read_wslconfig_missing_or_corrupt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(env_probe, "wslconfig_path", lambda: tmp_path / "nope")
    assert env_probe.read_wslconfig_limits() == {}
    bad = tmp_path / ".wslconfig"
    bad.write_text("not an ini {{{")
    monkeypatch.setattr(env_probe, "wslconfig_path", lambda: bad)
    assert env_probe.read_wslconfig_limits() == {}


def test_write_wslconfig_keeps_backup(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / ".wslconfig"
    cfg.write_text("[wsl2]\nmemory=2GB\n")
    monkeypatch.setattr(env_probe, "wslconfig_path", lambda: cfg)
    env_probe.write_wslconfig("[wsl2]\nmemory=24GB\n")
    assert "24GB" in cfg.read_text()
    backup = cfg.with_suffix(".wslconfig.flowdesk-backup")
    assert "2GB" in backup.read_text()


def test_find_paraview_with_candidates(tmp_path) -> None:
    fake = tmp_path / "ParaView 6.0" / "bin" / "paraview.exe"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    assert env_probe.find_paraview([fake]) == fake
    assert env_probe.find_paraview([tmp_path / "missing.exe"]) in (None,
                                                                   env_probe.find_paraview())


def test_host_ram_readable_on_windows() -> None:
    import sys

    if sys.platform == "win32":
        ram = env_probe.host_ram_mb()
        assert ram is not None and ram > 1000


@pytest.mark.skipif(not _ENV.available, reason="needs a provisioned environment")
def test_full_probe_on_this_machine() -> None:
    report = env_probe.full_probe(_ENV)
    components = {r.component for r in report.rows}
    assert "OpenFOAM v2506" in components
    assert "MPI" in components
    openfoam_row = next(r for r in report.rows if r.component == "OpenFOAM v2506")
    assert openfoam_row.ok
    mpi_row = next(r for r in report.rows if r.component == "MPI")
    assert mpi_row.ok, mpi_row.detail
    resources = next(r for r in report.rows if r.component == "Compute resources")
    assert "cores" in resources.detail
