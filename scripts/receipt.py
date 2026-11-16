#!/usr/bin/env python3
"""Build seam counters and failure ledger; never inspect credentials or mail."""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event(stage, result, detail):
    root = Path(os.environ.get("ARTIFACT_DIR", "/artifacts"))
    root.mkdir(parents=True, exist_ok=True)
    row = dict(
        time=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        result=result,
        detail=detail,
    )
    with (root / "build-ledger.jsonl").open("a") as output:
        output.write(json.dumps(row, sort_keys=True) + "\n")
    status_path = root / "build-status.json"
    status = (
        json.loads(status_path.read_text())
        if status_path.exists()
        else {"counters": {}}
    )
    key = f"{stage}:{result}"
    status["counters"][key] = status["counters"].get(key, 0) + 1
    status["last"] = row
    temporary = status_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    temporary.replace(status_path)
    print(f"stage={stage} result={result} {detail}", flush=True)


def manifest(project, root):
    project, root = Path(project), Path(root)
    source_files = [
        p
        for directory in ("scripts", "rpm", "patches", "examples", "tests")
        for p in (project / directory).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    source_files += [
        project / "target.env",
        project / "Dockerfile",
        project / "Dockerfile.lab",
    ]
    if (project / "candidate-context.json").exists():
        source_files += [project / "candidate-context.json", project / "target.diff"]
    revision = os.environ.get("SOURCE_REVISION", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source snapshot has no validated Git revision")
    artifacts = {
        str(p.relative_to(root)): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and (p.suffix == ".rpm" or ".so" in p.name)
    }
    document = {
        "schema": 1,
        "target": os.environ["DOVECOT_NVR"],
        "epoch": os.environ["DOVECOT_EPOCH"],
        "architecture": os.environ["TARGET_ARCH"],
        "source_revision": revision,
        "source_files": {
            str(p.relative_to(project)): digest(p) for p in sorted(source_files)
        },
        "artifacts": artifacts,
        "production_ready": False,
        "inputs": {
            str(p.relative_to(root)): digest(p)
            for p in sorted((root / "inputs").rglob("*"))
            if p.is_file()
        },
        "signature_policy": "Alma input signatures checked; custom candidate requires signing before promotion",
    }
    (root / "manifest.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    if sys.argv[1] == "event":
        event(*sys.argv[2:])
    elif sys.argv[1] == "manifest":
        manifest(*sys.argv[2:])
    else:
        raise SystemExit("unknown receipt operation")
