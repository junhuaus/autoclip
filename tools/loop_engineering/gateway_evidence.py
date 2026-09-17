"""Expose verified current Runner evidence to a read-only Gateway session.

The canonical QA, logs and execution snapshots remain in trusted outer storage.
This ignored, immutable-for-the-role copy is only an inspection surface; the
deterministic Gateway still verifies the canonical files after the role exits.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import LoopConfig
from .contracts import RunState
from .gateway import evaluate_gateway
from .store import file_identity, fingerprint_worktree, head_sha


@dataclass(frozen=True)
class GatewayEvidence:
    path: Path
    relative_path: str
    index_sha256: str
    identities: dict[str, str]

    def verify_unchanged(self) -> None:
        current = _bundle_identities(self.path)
        if current != self.identities:
            raise OSError("Gateway changed its read-only Runner evidence bundle")


def _bundle_identities(bundle: Path) -> dict[str, str]:
    return {
        str(path.relative_to(bundle)) or ".": file_identity(path)
        for path in (bundle, *bundle.rglob("*"))
    }


def prepare_gateway_evidence(
    config: LoopConfig,
    state: RunState,
    review: dict[str, Any],
    assurance: Path,
    *,
    toolchain_fingerprint: str,
) -> GatewayEvidence:
    """Make only this run's already correlated QA/log records role-visible."""

    decision = evaluate_gateway(
        config,
        review,
        {"verdict": "PASS", "route": "DONE"},  # Deterministic precheck, not a role verdict.
        state.command_results,
        current_head=head_sha(assurance),
        current_worktree=fingerprint_worktree(assurance),
        current_toolchain=toolchain_fingerprint,
        verify_files=True,
    )
    if not decision.passed:
        raise OSError(f"current Runner evidence failed pre-Gateway checks: {decision.reasons}")

    parent = assurance / ".loop" / "gateway-evidence"
    if parent.exists() or parent.is_symlink():
        raise OSError("Gateway evidence parent already exists")
    parent.mkdir(parents=True, mode=0o700)
    bundle = parent / state.run_id
    bundle.mkdir(mode=0o700)

    pipeline = (config.root / "qa/pipeline.jsonl").read_text(encoding="utf-8").splitlines()
    report = (config.root / "qa/test-report.md").read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    for result in state.command_results:
        qa_id = result["qa_id"]
        matches = [line for line in pipeline if json.loads(line).get("id") == qa_id]
        if len(matches) != 1:
            raise OSError("current Gateway QA request is not unique")
        headings = list(re.finditer(rf"(?m)^### {re.escape(qa_id)}$", report))
        if len(headings) != 1:
            raise OSError("current Gateway QA report is not unique")
        following = re.search(r"(?m)^### ", report[headings[0].end() :])
        end = headings[0].end() + following.start() if following else len(report)
        report_entry = report[headings[0].start() : end]

        log = config.root / result["log_path"]
        log_bytes = log.read_bytes()
        if len(log_bytes) > config.log_limit_bytes:
            raise OSError("current Runner log exceeds the bounded evidence limit")
        directory = bundle / result["command_id"]
        directory.mkdir(mode=0o700)
        payloads = {
            "runner.log": log_bytes,
            "qa-request.json": (matches[0] + "\n").encode("utf-8"),
            "qa-report.md": report_entry.encode("utf-8"),
            "command-result.json": (json.dumps(result, sort_keys=True, indent=2) + "\n").encode(
                "utf-8"
            ),
        }
        for name, payload in payloads.items():
            target = directory / name
            with target.open("xb") as stream:
                stream.write(payload)
            target.chmod(0o444)
        directory.chmod(0o555)
        records.append(
            {
                "command_id": result["command_id"],
                "qa_id": qa_id,
                "files": {
                    name: {
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size_bytes": len(payload),
                    }
                    for name, payload in payloads.items()
                },
            }
        )

    index = {
        "schema_version": "1",
        "run_id": state.run_id,
        "head": head_sha(assurance),
        "source_fingerprint": fingerprint_worktree(assurance),
        "toolchain_fingerprint": toolchain_fingerprint,
        "deterministic_canonical_evidence_precheck": "PASS",
        "note": "Semantic verdict and independent publication audit remain separate.",
        "commands": records,
    }
    index_bytes = (json.dumps(index, sort_keys=True, indent=2) + "\n").encode("utf-8")
    index_path = bundle / "index.json"
    with index_path.open("xb") as stream:
        stream.write(index_bytes)
    index_path.chmod(0o444)
    bundle.chmod(0o555)
    parent.chmod(0o555)
    identities = _bundle_identities(bundle)
    return GatewayEvidence(
        path=bundle,
        relative_path=str(bundle.relative_to(assurance)),
        index_sha256=hashlib.sha256(index_bytes).hexdigest(),
        identities=identities,
    )
