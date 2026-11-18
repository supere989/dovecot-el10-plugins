#!/usr/bin/env python3
import hashlib
import json
import re
import sys
from pathlib import Path


def validate(root, expected_target):
    root = Path(root).resolve()
    context = json.loads((root / "candidate-context.json").read_text())
    if (
        context.get("schema_version") != 1
        or context.get("target_nvr") != expected_target
    ):
        raise ValueError("candidate context differs from the selected target")
    revision = context.get("source_revision", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("candidate context lacks an immutable source revision")
    if not context.get("source_files") or context.get("promoted") is not False:
        raise ValueError("candidate context must be unpromoted with source evidence")
    actual = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path != root / "candidate-context.json"
    }
    if actual != set(context["source_files"]):
        raise ValueError("candidate source file inventory changed after preparation")
    for relative, expected in context["source_files"].items():
        path = root / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("candidate source path escapes its workspace")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("candidate source was edited after preparation")
    return revision


if __name__ == "__main__":
    print(validate(*sys.argv[1:]))
