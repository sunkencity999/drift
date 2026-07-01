"""Tests for the collector plugins.

Each collector must: expose name/is_available()/collect(), return a JSON-serializable
dict, and no-op (is_available()==False) when its backend is missing. Tests fake the
backends (subprocess.run, shutil.which) so they run anywhere.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from drift.plugins.base import CollectorError, registry
from drift.plugins.cron import CronCollector
from drift.plugins.packages import PackagesCollector
from drift.plugins.ports import PortsCollector
from drift.plugins.services import ServicesCollector
from drift.plugins.users import UsersCollector

# ---- protocol / registry ----------------------------------------------------


def test_all_collectors_satisfy_protocol():
    for cls in [
        PortsCollector, ServicesCollector, PackagesCollector,
        UsersCollector, CronCollector,
    ]:
        inst = cls()
        assert hasattr(inst, "name")
        assert callable(inst.is_available)
        assert callable(inst.collect)


def test_collector_names_are_stable():
    assert PortsCollector().name == "ports"
    assert ServicesCollector().name == "services"
    assert PackagesCollector().name == "packages"
    assert UsersCollector().name == "users"
    assert CronCollector().name == "cron"


def test_registry_discovers_all_five():
    names = {c.name for c in registry.all()}
    assert {"ports", "services", "packages", "users", "cron"} <= names


# ---- ports ------------------------------------------------------------------


def test_ports_unavailable_when_no_tool(monkeypatch):
    # neither lsof nor ss present
    monkeypatch.setattr("shutil.which", lambda b: None)
    assert PortsCollector().is_available() is False


def test_ports_collect_normalized_shape_macos(monkeypatch):
    """lsof output is normalized to a list of {proto, port, proc} regardless of OS."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/sbin/lsof" if b == "lsof" else None)
    fake_lsof = (
        "python   123 user   6u  IPv4 0x1  TCP *:8080 (LISTEN)\n"
        "nginx    456 user   7u  IPv6 0x2  TCP *:443 (LISTEN)\n"
    )
    with patch("drift.plugins.ports.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_lsof, stderr="")
        sample = PortsCollector().collect()
    assert "listeners" in sample
    ports = {(e["port"], e["proto"]) for e in sample["listeners"]}
    assert (8080, "tcp") in ports
    assert (443, "tcp") in ports
    json.dumps(sample)


def test_ports_collect_normalized_shape_linux(monkeypatch):
    """ss output is normalized to the same {proto, port, proc} shape as lsof."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/sbin/ss" if b == "ss" else None)
    fake_ss = (
        "LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* users:((\"python\",pid=123,fd=6))\n"
        "LISTEN 0 128 *:443       *:*       users:((\"nginx\",pid=456,fd=7))\n"
    )
    with patch("drift.plugins.ports.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_ss, stderr="")
        sample = PortsCollector().collect()
    ports = {(e["port"], e["proto"]) for e in sample["listeners"]}
    assert (8080, "tcp") in ports
    assert (443, "tcp") in ports


def test_ports_collect_raises_when_not_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    with pytest.raises(CollectorError):
        PortsCollector().collect()


# ---- services ---------------------------------------------------------------


def test_services_unavailable_when_no_tool(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    assert ServicesCollector().is_available() is False


def test_services_collect_macos(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/bin/launchctl" if b == "launchctl" else None)
    fake_launchctl = "PID\tStatus\tLabel\n123\t0\tcom.apple.sshd\n-\t0\tdev.mechanic.sampler\n"
    with patch("drift.plugins.services.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_launchctl, stderr="")
        sample = ServicesCollector().collect()
    assert "labels" in sample
    assert "com.apple.sshd" in sample["labels"]
    json.dumps(sample)


def test_services_collect_linux(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda b: "/usr/bin/systemctl" if b == "systemctl" else None,
    )
    fake_systemctl = (
        "ssh.service loaded active running OpenSSH\n"
        "nginx.service loaded active running nginx\n"
    )
    with patch("drift.plugins.services.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_systemctl, stderr="")
        sample = ServicesCollector().collect()
    assert "units" in sample
    assert "ssh.service" in sample["units"]


# ---- packages ---------------------------------------------------------------


def test_packages_unavailable_when_no_manager(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    assert PackagesCollector().is_available() is False


def test_packages_collect_brew(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/opt/homebrew/bin/brew" if b == "brew" else None)
    with patch("drift.plugins.packages.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="nginx\nopenssl\npython\n", stderr="",
        )
        sample = PackagesCollector().collect()
    assert sample["manager"] == "brew"
    assert "nginx" in sample["installed"]
    json.dumps(sample)


def test_packages_collect_dpkg(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda b: "/usr/bin/dpkg-query" if b == "dpkg-query" else None,
    )
    with patch("drift.plugins.packages.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="nginx\nopenssl\n", stderr="")
        sample = PackagesCollector().collect()
    assert sample["manager"] == "dpkg"
    assert "nginx" in sample["installed"]


# ---- users ------------------------------------------------------------------


def test_users_unavailable_when_no_source(monkeypatch):
    # neither dscl nor /etc/passwd readable paths — simulate by patching
    monkeypatch.setattr("shutil.which", lambda b: None)
    with patch("drift.plugins.users.Path") as mock_path:
        mock_path.return_value.exists.return_value = False
        assert UsersCollector().is_available() is False


def test_users_collect_macos(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/dscl" if b == "dscl" else None)
    fake_dscl = "christopher\nroot\ndaemon\n"
    with patch("drift.plugins.users.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_dscl, stderr="")
        sample = UsersCollector().collect()
    assert "users" in sample
    assert "christopher" in sample["users"]
    json.dumps(sample)


def test_users_collect_linux(monkeypatch):
    """On Linux, users come from /etc/passwd — no subprocess needed."""
    monkeypatch.setattr("shutil.which", lambda b: None)
    import drift.plugins.users as users_mod

    fake_passwd = (
        "root:x:0:0:root:/root:/bin/bash\n"
        "christopher:x:1000:1000::/home/christopher:/bin/zsh\n"
    )
    with patch.object(users_mod, "Path") as mock_path_cls:
        instance = MagicMock()
        instance.exists.return_value = True
        instance.read_text.return_value = fake_passwd
        mock_path_cls.return_value = instance
        sample = UsersCollector().collect()
    assert "christopher" in sample["users"]


# ---- cron -------------------------------------------------------------------


def test_cron_collect_macos(monkeypatch, tmp_path):
    """On macOS, cron = crontab -l (if any) + user launchd agents."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/crontab" if b == "crontab" else None)
    # hermetic: fake the agents dir with one plist
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "dev.mechanic.sampler.plist").write_text("<plist/>")
    monkeypatch.setattr("drift.plugins.cron._USER_AGENTS", agents_dir)
    monkeypatch.setattr("drift.plugins.cron._CRON_D", tmp_path / "no-cron-d")
    with patch("drift.plugins.cron.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="0 9 * * * /usr/bin/foo\n", stderr=""),
        ]
        sample = CronCollector().collect()
    assert "entries" in sample
    assert any("0 9 * * *" in e for e in sample["entries"])
    assert "agents" in sample
    assert "dev.mechanic.sampler.plist" in sample["agents"]
    json.dumps(sample)


def test_cron_collect_empty_crontab(monkeypatch, tmp_path):
    """No crontab and no launchd agents is a normal state, not an error."""
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/crontab" if b == "crontab" else None)
    # point the agent/cron.d paths at empty/nonexistent dirs so the test is hermetic
    monkeypatch.setattr("drift.plugins.cron._USER_AGENTS", tmp_path / "no-agents")
    monkeypatch.setattr("drift.plugins.cron._CRON_D", tmp_path / "no-cron-d")
    with patch("drift.plugins.cron.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="no crontab"),  # no crontab
        ]
        sample = CronCollector().collect()
    assert sample["entries"] == []
    assert sample["agents"] == []
    assert sample["cron_d"] == []
