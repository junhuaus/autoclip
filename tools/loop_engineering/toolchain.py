from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .process import safe_child_env
from .store import fingerprint_worktree
from .tokenizer_cache import CACHE_PATH, validate_cache

TOOLCHAIN_COMPONENTS = (
    Path(".python"),
    Path(".venv"),
    Path("apps/web/node_modules"),
    CACHE_PATH,
    Path(".cache/playwright"),
)
TOOLCHAIN_LOCKS = (
    Path("Makefile"),
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("apps/web/package.json"),
    Path("apps/web/package-lock.json"),
)
MUTABLE_NODE_PATHS = {Path("apps/web/node_modules/.vite"), Path("apps/web/node_modules/.vite-temp")}
PRESERVED_CONTROL_PATHS = {Path("qa/pipeline.jsonl"), Path("qa/test-report.md")}
TOOLCHAIN_FORMAT_VERSION = 2
# Recording helper revision from the locked playwright-core/browsers.json.
PLAYWRIGHT_FFMPEG = Path(".cache/playwright/ffmpeg-1011/ffmpeg-mac")


class ToolchainError(OSError):
    pass


@dataclass(frozen=True)
class TrustedToolchain:
    path: Path
    fingerprint: str
    source_fingerprint: str


@dataclass(frozen=True)
class ExecutionSnapshot:
    path: Path
    source_fingerprint: str


class ToolchainManager:
    def __init__(self, root: Path, cache_root: Path | None = None) -> None:
        self.root = root.resolve()
        root_id = hashlib.sha256(os.fsencode(str(self.root))).hexdigest()[:16]
        self.cache_root = (
            cache_root.resolve()
            if cache_root is not None
            else Path.home() / "Library/Caches/LiveClip/loop-toolchains" / root_id
        )

    def readiness_issues(self) -> list[str]:
        issues: list[str] = []
        try:
            validate_cache(self.root)
        except OSError:
            issues.append("tokenizer cache is missing, unsafe or corrupt; run make setup")
        for relative in TOOLCHAIN_COMPONENTS:
            path = self.root / relative
            if not path.is_dir() or path.is_symlink():
                issues.append(f"toolchain directory is missing or unsafe: {relative}")
        python = self.root / ".venv/bin/python"
        if python.exists():
            try:
                completed = subprocess.run(
                    [str(python), "-c", "import sys; print(sys.executable)"],
                    cwd=self.root,
                    env=safe_child_env(),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                executable = Path(completed.stdout.strip()).resolve(strict=True)
                if completed.returncode != 0 or not executable.is_relative_to(self.root):
                    issues.append("project Python resolves outside the repository")
            except (OSError, subprocess.TimeoutExpired):
                issues.append("project Python identity could not be verified")
        else:
            issues.append("project Python is missing")
        for relative in (Path(".venv/bin/ruff"), Path(".venv/bin/mypy"), PLAYWRIGHT_FFMPEG):
            path = self.root / relative
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                issues.append(f"tool executable is missing: {relative}")
            else:
                if not resolved.is_relative_to(self.root):
                    issues.append(f"tool executable resolves outside the repository: {relative}")
                elif not resolved.is_file() or not os.access(resolved, os.X_OK):
                    issues.append(f"tool executable is not a regular executable: {relative}")
        try:
            _assert_safe_tree(self.root)
        except ToolchainError as exc:
            issues.append(str(exc))
        return issues

    def prepare(self) -> TrustedToolchain:
        issues = self.readiness_issues()
        if issues:
            raise ToolchainError("; ".join(issues))
        before = toolchain_fingerprint(self.root)
        destination = self.cache_root / f"v{TOOLCHAIN_FORMAT_VERSION}" / before
        if destination.exists():
            if not destination.is_dir() or destination.is_symlink():
                raise ToolchainError("trusted toolchain cache path is unsafe")
            snapshot_fingerprint = _snapshot_manifest(destination, before)
            if toolchain_fingerprint(destination) != snapshot_fingerprint:
                raise ToolchainError("trusted toolchain cache fingerprint mismatch")
            return TrustedToolchain(destination, snapshot_fingerprint, before)

        self.cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = destination.parent / f".{before}.{os.getpid()}.tmp"
        staging.mkdir(mode=0o700, exist_ok=False)
        try:
            for relative in (*TOOLCHAIN_LOCKS, *TOOLCHAIN_COMPONENTS):
                source = self.root / relative
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target, symlinks=True)
                else:
                    shutil.copy2(source, target, follow_symlinks=False)
            _rewrite_absolute_symlinks(self.root, staging)
            after = toolchain_fingerprint(self.root)
            copied = toolchain_fingerprint(staging)
            if before != after or copied != before:
                raise ToolchainError("toolchain changed while the trusted snapshot was created")
            _rewrite_embedded_paths(self.root, destination, staging)
            snapshot_fingerprint = toolchain_fingerprint(staging)
            (staging / "snapshot.json").write_text(
                json.dumps(
                    {
                        "format_version": TOOLCHAIN_FORMAT_VERSION,
                        "source_fingerprint": before,
                        "snapshot_fingerprint": snapshot_fingerprint,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            _seal_tree(staging)
            try:
                staging.rename(destination)
            except FileExistsError:
                existing_fingerprint = _snapshot_manifest(destination, before)
                if toolchain_fingerprint(destination) != existing_fingerprint:
                    raise ToolchainError("concurrent trusted toolchain snapshot differs") from None
                _make_writable(staging)
                shutil.rmtree(staging)
        except BaseException:
            if staging.exists():
                _make_writable(staging)
                shutil.rmtree(staging)
            raise
        return TrustedToolchain(destination, snapshot_fingerprint, before)

    def execution_snapshot(
        self,
        toolchain: TrustedToolchain,
        run_id: str,
        qa_id: str,
        expected_worktree: str,
        *,
        source_root: Path | None = None,
    ) -> ExecutionSnapshot:
        source_root = (source_root or self.root).resolve(strict=True)
        trusted = toolchain.path.resolve(strict=True)
        if trusted.is_relative_to(self.root):
            raise ToolchainError("trusted toolchain must be outside the Coder workspace")
        if toolchain_fingerprint(trusted) != toolchain.fingerprint:
            raise ToolchainError("trusted toolchain snapshot changed")
        if _paths_fingerprint(source_root, list(TOOLCHAIN_LOCKS)) != _paths_fingerprint(
            trusted, list(TOOLCHAIN_LOCKS)
        ):
            raise ToolchainError("toolchain lock or Make gate changed after policy freeze")
        destination = self.cache_root / "executions" / run_id / qa_id
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.mkdir(mode=0o700, exist_ok=False)
        try:
            paths = _repository_paths(source_root)
            head_before = _head(source_root)
            before = _paths_fingerprint(source_root, paths)
            _copy_paths(source_root, destination, paths)
            copied = _paths_fingerprint(destination, paths)
            after = _paths_fingerprint(source_root, paths)
            if before != copied or before != after:
                raise ToolchainError("repository changed while the execution snapshot was created")
            shutil.copytree(source_root / ".git", destination / ".git", symlinks=True)
            if _head(destination) != head_before or _head(source_root) != head_before:
                raise ToolchainError("Git HEAD changed while the execution snapshot was created")
            execution_worktree = fingerprint_worktree(destination)
            if execution_worktree != expected_worktree:
                raise ToolchainError("execution snapshot does not match the pre-run worktree")
            (destination / ".venv").symlink_to(trusted / ".venv", target_is_directory=True)
            if (trusted / ".python").is_dir():
                (destination / ".python").symlink_to(trusted / ".python", target_is_directory=True)
            node_target = destination / "apps/web/node_modules"
            _copy_node_dependencies(trusted / "apps/web/node_modules", node_target)
            for relative in (Path("apps/web/test-results"), Path("apps/web/playwright-report")):
                (destination / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
        except BaseException:
            _make_writable(destination)
            shutil.rmtree(destination)
            raise
        return ExecutionSnapshot(destination, execution_worktree)

    def publish_snapshot(
        self,
        snapshot: Path,
        *,
        expected_source_worktree: str,
        expected_snapshot_worktree: str,
    ) -> None:
        snapshot = snapshot.resolve(strict=True)
        if snapshot.is_relative_to(self.root):
            raise ToolchainError("candidate snapshot must be outside the delivery workspace")
        if _head(snapshot) != _head(self.root):
            raise ToolchainError("candidate and delivery Git HEAD differ")
        if fingerprint_worktree(self.root) != expected_source_worktree:
            raise ToolchainError("delivery workspace changed while Coder was isolated")
        if fingerprint_worktree(snapshot) != expected_snapshot_worktree:
            raise ToolchainError("accepted candidate snapshot changed before publication")
        source_paths = set(_repository_paths(self.root))
        candidate_paths = set(_repository_paths(snapshot))
        for relative in sorted(candidate_paths, key=lambda item: os.fsencode(str(item))):
            source = snapshot / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.publish")
            if source.is_symlink():
                resolved = source.resolve(strict=True)
                mapped = self.root / resolved.relative_to(snapshot)
                temporary.symlink_to(
                    os.path.relpath(mapped, temporary.parent), target_is_directory=resolved.is_dir()
                )
            else:
                shutil.copy2(source, temporary)
            os.replace(temporary, target)
        for relative in sorted(
            source_paths - candidate_paths,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            target = self.root / relative
            if target.is_file() or target.is_symlink():
                target.unlink()
        if fingerprint_worktree(self.root) != expected_snapshot_worktree:
            raise ToolchainError("published workspace does not match the accepted candidate")


def toolchain_fingerprint(root: Path) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    for relative in (*TOOLCHAIN_LOCKS, *TOOLCHAIN_COMPONENTS):
        _hash_path(digest, root, relative)
    return digest.hexdigest()


def _hash_path(digest: hashlib._Hash, root: Path, relative: Path) -> None:
    path = root / relative
    digest.update(os.fsencode(str(relative)))
    digest.update(b"\0")
    if any(relative == value or relative.is_relative_to(value) for value in MUTABLE_NODE_PATHS):
        digest.update(b"mutable\0")
        return
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        digest.update(b"missing\0")
        return
    if stat.S_ISLNK(metadata.st_mode):
        target = path.resolve(strict=True)
        if not target.is_relative_to(root):
            raise ToolchainError(f"toolchain symlink escapes repository: {relative}")
        digest.update(b"symlink\0")
        digest.update(os.fsencode(str(target.relative_to(root))))
        return
    if stat.S_ISREG(metadata.st_mode):
        digest.update(b"regular\0")
        digest.update(str(metadata.st_mode & 0o111).encode())
        with path.open("rb") as handle:
            while chunk := handle.read(1_048_576):
                digest.update(chunk)
        return
    if not stat.S_ISDIR(metadata.st_mode):
        raise ToolchainError(f"toolchain has unsupported file type: {relative}")
    digest.update(b"directory\0")
    for child in sorted(path.iterdir(), key=lambda item: os.fsencode(item.name)):
        _hash_path(digest, root, child.relative_to(root))


def _assert_safe_tree(root: Path) -> None:
    toolchain_fingerprint(root)


def _rewrite_absolute_symlinks(source_root: Path, snapshot_root: Path) -> None:
    for path in snapshot_root.rglob("*"):
        if not path.is_symlink():
            continue
        original = source_root / path.relative_to(snapshot_root)
        target = original.resolve(strict=True)
        if not target.is_relative_to(source_root):
            raise ToolchainError(f"toolchain symlink escapes repository: {original}")
        path.unlink()
        mapped = snapshot_root / target.relative_to(source_root)
        path.symlink_to(os.path.relpath(mapped, path.parent), target_is_directory=target.is_dir())


def _rewrite_embedded_paths(source_root: Path, destination: Path, staging: Path) -> None:
    candidates = [staging / ".venv/pyvenv.cfg"]
    candidates.extend((staging / ".venv").rglob("*.pth"))
    candidates.extend((staging / ".venv").rglob("*.egg-link"))
    for path in candidates:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
            continue
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        replaced = value.replace(str(source_root), str(destination))
        if replaced != value:
            path.write_text(replaced, encoding="utf-8")
    _rewrite_python_entrypoints(source_root, destination, staging)


def _rewrite_python_entrypoints(source_root: Path, destination: Path, staging: Path) -> None:
    source_bin = source_root / ".venv/bin"
    interpreter = re.compile(re.escape(str(source_bin)) + r"/python(?:[0-9]+(?:\.[0-9]+)*)?")
    for path in (staging / ".venv/bin").iterdir():
        if not path.is_file() or path.is_symlink() or not path.stat().st_mode & 0o111:
            continue
        with path.open("rb") as handle:
            if handle.read(2) != b"#!":
                continue
        if path.stat().st_size > 1_000_000:
            raise ToolchainError(f"oversized toolchain script: {path.name}")
        value = path.read_bytes()
        lines = value.splitlines(keepends=True)
        first = lines[0].rstrip(b"\r\n").decode("utf-8")
        target = first[2:]
        if interpreter.fullmatch(target):
            mapped = str(destination / ".venv/bin" / Path(target).name)
            if any(character.isspace() for character in mapped) or len(mapped.encode()) > 250:
                raise ToolchainError(f"unsafe relocated Python shebang: {path.name}")
            ending = b"\r\n" if lines[0].endswith(b"\r\n") else b"\n"
            lines[0] = f"#!{mapped}".encode() + ending
        elif (
            first == "#!/bin/sh"
            and len(lines) >= 3
            and lines[1].startswith(b"'''exec' ")
            and lines[1].rstrip().endswith(b' "$0" "$@"')
            and lines[2].strip() == b"' '''"
        ):
            encoded = lines[1].strip()[len("'''exec' ") : -len(' "$0" "$@"')].decode()
            try:
                arguments = shlex.split(encoded)
            except ValueError as exc:
                raise ToolchainError(f"invalid Python trampoline: {path.name}") from exc
            if len(arguments) != 1 or interpreter.fullmatch(arguments[0]) is None:
                raise ToolchainError(f"nonlocal Python trampoline: {path.name}")
            mapped = str(destination / ".venv/bin" / Path(arguments[0]).name)
            ending = b"\r\n" if lines[1].endswith(b"\r\n") else b"\n"
            lines[1] = f"'''exec' {shlex.quote(mapped)} \"$0\" \"$@\"".encode() + ending
        else:
            if str(source_bin).encode() in b"".join(lines[:3]):
                raise ToolchainError(f"unsupported local toolchain entrypoint: {path.name}")
            continue
        path.write_bytes(b"".join(lines))


def _copy_node_dependencies(source: Path, target: Path) -> None:
    mutable_names = {path.name for path in MUTABLE_NODE_PATHS}
    shutil.copytree(
        source,
        target,
        symlinks=True,
        ignore=lambda directory, names: (
            mutable_names.intersection(names) if Path(directory) == source else set()
        ),
    )
    original_mode = target.stat().st_mode
    target.chmod(original_mode | stat.S_IWUSR)
    try:
        for name in mutable_names:
            (target / name).mkdir(mode=0o700)
    finally:
        target.chmod(original_mode)


def _snapshot_manifest(path: Path, expected_source: str) -> str:
    try:
        value = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolchainError("trusted toolchain snapshot manifest is invalid") from exc
    if not isinstance(value, dict) or value.get("source_fingerprint") != expected_source:
        raise ToolchainError("trusted toolchain snapshot source identity differs")
    if value.get("format_version") != TOOLCHAIN_FORMAT_VERSION:
        raise ToolchainError("trusted toolchain snapshot format differs")
    fingerprint = value.get("snapshot_fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ToolchainError("trusted toolchain snapshot identity is invalid")
    return fingerprint


def _repository_paths(root: Path) -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "."],
        cwd=root,
        check=True,
        capture_output=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "."],
        cwd=root,
        check=True,
        capture_output=True,
    )
    excluded = (Path("data"), Path(".loop"), *TOOLCHAIN_COMPONENTS)
    result: list[Path] = []
    values = [(raw, False) for raw in tracked.stdout.split(b"\0")]
    values.extend((raw, True) for raw in untracked.stdout.split(b"\0"))
    for raw, is_untracked in values:
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative in PRESERVED_CONTROL_PATHS:
            continue
        if is_untracked and any(
            relative == item or relative.is_relative_to(item) for item in excluded
        ):
            continue
        path = root / relative
        if path.is_symlink() and not path.resolve(strict=True).is_relative_to(root):
            raise ToolchainError(f"repository symlink escapes source root: {relative}")
        if path.is_file() or path.is_symlink():
            result.append(relative)
    return sorted(set(result), key=lambda item: os.fsencode(str(item)))


def _head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def _paths_fingerprint(root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        _hash_path(digest, root, relative)
    return digest.hexdigest()


def _copy_paths(source: Path, destination: Path, paths: list[Path]) -> None:
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if (source / relative).is_symlink():
            resolved = (source / relative).resolve(strict=True)
            mapped = destination / resolved.relative_to(source)
            target.symlink_to(
                os.path.relpath(mapped, target.parent), target_is_directory=resolved.is_dir()
            )
        else:
            shutil.copy2(source / relative, target)


def _seal_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod((mode & 0o555) or (0o555 if path.is_dir() else 0o444))
    root.chmod(0o555)


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    root.chmod(root.stat().st_mode | stat.S_IWUSR)
