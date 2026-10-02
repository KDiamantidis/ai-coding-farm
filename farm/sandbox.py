# =============================================================================
# FILE:    farm/sandbox.py
# PURPOSE: Run the task's test command inside a throw-away Docker container,
#          so code written by a model cannot reach the network, the host files,
#          or use all the memory/CPU of the machine.
#
# EXPORTS:
#   SandboxError                     setup problem (no Docker, no image). NOT a model failure.
#   from_settings(settings)          -> dict | None   (None = run on the host, as before)
#   docker_command(cfg, dir, argv)   -> the `docker run ...` argv (pure, easy to test)
#   run(cfg, dir, argv, timeout_s)   -> subprocess.CompletedProcess  (raises TimeoutExpired)
#   preflight(cfg)                   -> raises SandboxError early if Docker/image is missing
#   build_image(cfg)                 -> builds the image from docker/Dockerfile
#
# DESIGN NOTES:
#   - Network is OFF (`--network none`). Tests of our tasks need no internet.
#   - Only the temporary COPY of the repo is mounted, never the real repo.
#   - Memory, CPU, process count and a read-only root file system are limited.
#   - `--pull never`: a missing image is a clear setup error, not a slow download.
#   - Docker exit code 125 means Docker itself failed (not the tests). We turn it
#     into SandboxError, so it never counts against a model.
#   - On timeout we `docker rm -f` the named container. Killing only the client
#     process would leave the container running.
# =============================================================================

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

DEFAULT_IMAGE = "farm-sandbox:latest"
DOCKERFILE_DIR = Path(__file__).resolve().parent.parent / "docker"


class SandboxError(RuntimeError):
    """Docker is not usable. This says nothing about the model or the task."""


def from_settings(settings: dict) -> dict | None:
    """Read `settings.sandbox` from models.yaml. 'none' (default) means no Docker."""
    mode = str(settings.get("sandbox", "none")).lower()
    if mode == "none":
        return None
    if mode != "docker":
        raise SandboxError(f"settings.sandbox must be 'none' or 'docker', got '{mode}'")
    return {
        "image": settings.get("sandbox_image", DEFAULT_IMAGE),
        "memory": str(settings.get("sandbox_memory", "512m")),
        "cpus": str(settings.get("sandbox_cpus", "1")),
        "pids": int(settings.get("sandbox_pids", 256)),
        "network": str(settings.get("sandbox_network", "none")),
    }


def docker_command(cfg: dict, workdir: Path, argv: list[str], name: str) -> list[str]:
    cmd = [
        "docker", "run", "--rm", "--name", name, "--pull", "never",
        "--network", cfg["network"],
        "--memory", cfg["memory"], "--memory-swap", cfg["memory"],
        "--cpus", cfg["cpus"], "--pids-limit", str(cfg["pids"]),
        "--read-only", "--tmpfs", "/tmp:rw,size=64m",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp",
        "-v", f"{workdir}:/work", "-w", "/work",
    ]
    if hasattr(os, "getuid"):   # Linux/macOS: files in /work belong to you; Windows Docker Desktop handles it
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    return cmd + [cfg["image"]] + argv


def run(cfg: dict, workdir: Path, argv: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    # inside the image there is one python, called "python"
    if argv and argv[0] == "python3":
        argv = ["python"] + argv[1:]
    name = f"farm-{uuid.uuid4().hex[:12]}"
    try:
        proc = subprocess.run(docker_command(cfg, workdir, argv, name),
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        raise
    except FileNotFoundError:
        raise SandboxError("docker was not found. Install Docker or set "
                           "settings.sandbox to 'none' in models.yaml.") from None
    if proc.returncode == 125:   # docker itself failed (daemon down, image missing, bad flag)
        raise SandboxError("docker could not start the test container: "
                           + proc.stderr.strip()[-400:])
    return proc


def preflight(cfg: dict) -> None:
    """Fail early, before any model is paid or waited for."""
    try:
        r = subprocess.run(["docker", "image", "inspect", cfg["image"]],
                           capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise SandboxError("docker was not found. Install Docker or set "
                           "settings.sandbox to 'none' in models.yaml.") from None
    except subprocess.TimeoutExpired:
        raise SandboxError("docker did not answer within 30 seconds. Is Docker running?") from None
    if r.returncode != 0:
        raise SandboxError(f"docker image '{cfg['image']}' not found (or Docker is not running). "
                           "Build it once with:  python -m farm sandbox-build")


def build_image(cfg: dict) -> int:
    try:
        return subprocess.run(["docker", "build", "-t", cfg["image"], str(DOCKERFILE_DIR)]).returncode
    except FileNotFoundError:
        raise SandboxError("docker was not found.") from None
