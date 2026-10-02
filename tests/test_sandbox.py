# =============================================================================
# FILE:    tests/test_sandbox.py
# PURPOSE: Check the Docker sandbox WITHOUT Docker: a fake `subprocess.run`
#          records the command and returns what Docker would return.
#          Real-Docker tests are skipped when Docker is not running.
# =============================================================================

import shutil
import subprocess

import pytest

from farm import gatekeeper, sandbox

CFG = sandbox.from_settings({"sandbox": "docker"})


def completed(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


def test_default_is_no_docker():
    assert sandbox.from_settings({}) is None
    assert sandbox.from_settings({"sandbox": "none"}) is None


def test_bad_mode_is_a_clear_error():
    with pytest.raises(sandbox.SandboxError):
        sandbox.from_settings({"sandbox": "podman"})


def test_command_has_every_limit(tmp_path):
    cmd = sandbox.docker_command(CFG, tmp_path, ["python", "-m", "pytest", "-q"], "farm-x")
    joined = " ".join(cmd)
    for flag in ("--network none", "--memory 512m", "--memory-swap 512m", "--cpus 1",
                 "--pids-limit 256", "--read-only", "--cap-drop ALL",
                 "no-new-privileges", "--pull never", "--rm"):
        assert flag in joined
    assert f"{tmp_path}:/work" in joined
    assert cmd[-4:] == ["python", "-m", "pytest", "-q"]
    assert cmd[cmd.index("farm-sandbox:latest") - 1] != "-v"   # image comes right before the command


def test_tests_pass_and_fail_through_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(0))
    assert gatekeeper.run_tests(tmp_path, "python -m pytest", 5, CFG).passed
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(1, "FAILED test_x"))
    v = gatekeeper.run_tests(tmp_path, "python -m pytest", 5, CFG)
    assert v.reason == "tests_failed" and "FAILED test_x" in v.feedback


def test_docker_failure_is_not_blamed_on_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(125, "", "Cannot connect to the Docker daemon"))
    with pytest.raises(sandbox.SandboxError, match="Docker daemon"):
        gatekeeper.run_tests(tmp_path, "python -m pytest", 5, CFG)


def test_missing_docker_binary_is_a_setup_error(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("docker")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(sandbox.SandboxError, match="docker was not found"):
        gatekeeper.run_tests(tmp_path, "python -m pytest", 5, CFG)


def test_timeout_removes_the_container(tmp_path, monkeypatch):
    calls = []

    def fake(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(cmd, 1)
        return completed(0)
    monkeypatch.setattr(subprocess, "run", fake)
    v = gatekeeper.run_tests(tmp_path, "python -m pytest", 1, CFG)
    assert v.reason == "timeout"
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "rm", "-f", name]


def test_preflight_explains_the_missing_image(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(1))
    with pytest.raises(sandbox.SandboxError, match="sandbox-build"):
        sandbox.preflight(CFG)


def _docker_works():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", sandbox.DEFAULT_IMAGE],
                              capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_works(), reason="needs Docker and `python -m farm sandbox-build`")
def test_real_container_has_no_network_and_a_read_only_root(tmp_path):
    (tmp_path / "t.py").write_text(
        "import socket, pathlib, pytest\n"
        "def test_net():\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "def test_root_is_read_only():\n"
        "    with pytest.raises(OSError):\n"
        "        pathlib.Path('/etc/evil').write_text('x')\n"
        "def test_work_is_writable():\n"
        "    pathlib.Path('ok.txt').write_text('x')\n")
    assert gatekeeper.run_tests(tmp_path, "python -m pytest -q t.py", 60, CFG).passed


def test_run_stops_before_any_model_call_when_docker_is_not_ready(tmp_path, monkeypatch):
    from farm import db, orchestrator
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(1))
    cfg = {"settings": {"sandbox": "docker"}}
    with pytest.raises(sandbox.SandboxError):
        orchestrator.run_all(db.connect(str(tmp_path / "t.db")), cfg, tmp_path)
