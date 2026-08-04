"""Export or drift-check LiveClip's versioned EditPlan JSON Schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from liveclip.domain.edit_plan import EditPlan

_OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "edit-plan-v1.schema.json"


def rendered_schema() -> str:
    return (
        json.dumps(
            EditPlan.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the tracked schema")
    mode.add_argument("--check", action="store_true", help="fail if the tracked schema drifted")
    arguments = parser.parse_args()
    expected = rendered_schema()
    if arguments.write:
        _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        _OUTPUT.write_text(expected, encoding="utf-8")
        print(_OUTPUT)
        return 0
    if arguments.check:
        if not _OUTPUT.is_file() or _OUTPUT.read_text(encoding="utf-8") != expected:
            print("EditPlan JSON Schema drifted; run `make schema`", flush=True)
            return 1
        print(f"EditPlan JSON Schema: {_OUTPUT.name} matches the domain model")
        return 0
    print(expected, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
