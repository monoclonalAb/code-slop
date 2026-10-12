"""Thin wrapper around `docker run` for agent and evaluation containers."""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from codeslop.config import CACHE_DIR
from codeslop.config import IMAGE
from codeslop.config import PI_VERSION
from codeslop.config import REPO_ROOT


@dataclass
class DockerResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def docker_ok() -> bool:
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def image_exists(image: str = IMAGE) -> bool:
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def build_image(image: str = IMAGE) -> None:
    subprocess.run(["docker", "build", "--build-arg", f"PI_VERSION={PI_VERSION}", "-t", image,
                    "-f", str(REPO_ROOT / "docker" / "Dockerfile"), str(REPO_ROOT / "docker")],
                   check=True)


def run(cmd: list[str], *, mounts: dict[Path, str], workdir: str = "/workspace",
        env: dict[str, str] | None = None, secret_env: dict[str, str] | None = None,
        timeout: float | None = None, cpus: str = "2", memory: str = "4g",
        image: str = IMAGE) -> DockerResult:
    """Run `cmd` in a fresh container as the host uid. mounts: host path -> 'container[:ro]'.

    secret_env values are passed through the docker CLI's environment (`-e NAME`), so they never
    appear in argv / `ps`."""
    name = f"codeslop-{uuid.uuid4().hex[:12]}"
    cache = CACHE_DIR / "docker-cache"
    (cache / "uv").mkdir(parents=True, exist_ok=True)
    (cache / "pip").mkdir(parents=True, exist_ok=True)
    args = ["docker", "run", "--rm", "--name", name, "--user", f"{os.getuid()}:{os.getgid()}",
            "--cpus", cpus, "--memory", memory, "--pids-limit", "1024", "-w", workdir,
            "-v", f"{cache}:/cache"]
    for host, target in mounts.items():
        args += ["-v", f"{Path(host).resolve()}:{target}"]
    for k, v in (env or {}).items():
        args += ["-e", f"{k}={v}"]
    for k in secret_env or {}:
        args += ["-e", k]
    args += [image, *cmd]
    proc_env = {**os.environ, **(secret_env or {})}
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=proc_env)
        return DockerResult(proc.returncode, proc.stdout, proc.stderr, False)
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "kill", name], capture_output=True)
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return DockerResult(124, out, err, True)
