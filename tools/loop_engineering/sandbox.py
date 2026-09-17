from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class SandboxError(OSError):
    pass


@dataclass(frozen=True)
class SandboxedCommand:
    argv: list[str]
    env: dict[str, str]


def sandbox_executable() -> Path:
    expected = Path("/usr/bin/sandbox-exec")
    if not expected.is_file() or expected.is_symlink():
        raise SandboxError("macOS sandbox-exec is unavailable or unsafe")
    return expected


def resolve_command(executable: str, env: dict[str, str]) -> Path:
    candidate = shutil.which(executable, path=env.get("PATH"))
    if candidate is None:
        raise SandboxError(f"allowlisted executable was not found: {executable}")
    resolved = Path(candidate).resolve(strict=True)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise SandboxError(f"allowlisted executable is not a regular executable: {resolved}")
    return resolved


@contextmanager
def runner_sandbox(
    root: Path,
    argv: list[str],
    env: dict[str, str],
    *,
    execution_root: Path | None = None,
    toolchain_root: Path | None = None,
) -> Iterator[SandboxedCommand]:
    """Wrap a fixed command in a deny-default macOS Seatbelt sandbox."""

    if not argv:
        raise SandboxError("allowlisted argv is empty")
    root = root.resolve(strict=True)
    execution_root = (execution_root or root).resolve(strict=True)
    toolchain_root = (toolchain_root or execution_root).resolve(strict=True)
    command = resolve_command(argv[0], env)
    sandbox = sandbox_executable()
    with tempfile.TemporaryDirectory(prefix="liveclip-runner-") as temporary:
        temp_root = Path(temporary).resolve()
        home = temp_root / "home"
        scratch = temp_root / "tmp"
        home.mkdir(mode=0o700)
        scratch.mkdir(mode=0o700)
        profile = temp_root / "runner.sb"
        profile.write_text(
            _profile(root, temp_root, execution_root, toolchain_root), encoding="utf-8"
        )
        profile.chmod(0o600)
        child_env = dict(env)
        child_env.update(
            {
                "HOME": str(home),
                "TMPDIR": str(scratch),
                "MAC_CHROMIUM_TMPDIR": str(scratch),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "RUFF_CACHE_DIR": str(scratch / "ruff"),
                "MYPY_CACHE_DIR": str(scratch / "mypy"),
                "TIKTOKEN_CACHE_DIR": str(toolchain_root / ".cache/tiktoken"),
                "PLAYWRIGHT_BROWSERS_PATH": str(toolchain_root / ".cache/playwright"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(execution_root / "src"),
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            }
        )
        child_env["PYTEST_ADDOPTS"] = (
            f"{child_env.get('PYTEST_ADDOPTS', '')} -p no:cacheprovider".strip()
        )
        child_env.pop("CODEX_HOME", None)
        yield SandboxedCommand(
            [str(sandbox), "-f", str(profile), str(command), *argv[1:]],
            child_env,
        )


def _profile(
    root: Path,
    temp_root: Path,
    execution_root: Path | None = None,
    toolchain_root: Path | None = None,
) -> str:
    execution_root = execution_root or root
    toolchain_root = toolchain_root or execution_root

    def quote(value: Path) -> str:
        return json.dumps(str(value))

    protected = [
        root / ".git",
        root / ".loop",
        root / "qa",
        execution_root / ".git",
    ]
    repository_credentials = [
        root / name
        for name in (".env", ".env.local", ".env.development", ".env.test", ".env.production")
    ]
    writable = [
        execution_root / "apps" / "web" / "node_modules" / ".vite",
        execution_root / "apps" / "web" / "node_modules" / ".vite-temp",
        execution_root / "apps" / "web" / "playwright-report",
        execution_root / "apps" / "web" / "test-results",
        temp_root,
    ]
    home = Path.home()
    readable = (root, execution_root, toolchain_root)
    ancestors = {
        parent for path in readable for parent in path.parents if parent.is_relative_to(home)
    }
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        r'(allow mach-register (global-name-regex #"^com\.google\.Chrome\.'
        r'MachPortRendezvousServer\.[0-9]+$"))',
        "(allow ipc-posix*)",
        '(allow iokit-open (iokit-registry-entry-class "RootDomainUserClient"))',
        f"(allow file-read* (require-not (subpath {quote(home)})))",
        '(allow file-write-data (literal "/dev/null"))',
        "(allow network-bind (local ip))",
        "(allow network-inbound (local ip))",
        '(allow network-outbound (remote ip "localhost:*"))',
        "(allow system-socket (socket-domain AF_UNIX))",
        f"(allow network-bind (local unix-socket (subpath {quote(temp_root / 'tmp')})))",
        f"(allow network-outbound (remote unix-socket (subpath {quote(temp_root / 'tmp')})))",
    ]
    lines.extend(f"(allow file-read* (subpath {quote(path)}))" for path in readable)
    lines.extend(
        f"(allow file-read-metadata (require-all (literal {quote(path)}) (vnode-type DIRECTORY)))"
        for path in sorted(ancestors)
    )
    lines.extend(f"(allow file-write* (subpath {quote(path)}))" for path in writable)
    lines.extend(f"(deny file-write* (subpath {quote(path)}))" for path in protected)
    lines.extend(
        f"(deny file-read* file-write* (literal {quote(path)}))" for path in repository_credentials
    )
    return "\n".join(lines) + "\n"
