"""Apply only recorded native test harness corrections after production install."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PATCHES = (
    "upstream-test-failures-parent-pipe.patch",
    "test-lib-process-title-init.patch",
)


def prepare(project, core, output):
    project, core, output = Path(project), Path(core), Path(output)
    receipts = []
    for name in PATCHES:
        path = project / "patches" / name
        command = ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(path)]
        forward = subprocess.run(
            command + ["--forward", "--dry-run"],
            cwd=core,
            capture_output=True,
            text=True,
        )
        if forward.returncode == 0:
            subprocess.run(command + ["--forward"], cwd=core, check=True)
            state = "applied"
        else:
            reverse = subprocess.run(
                command + ["--reverse", "--dry-run"],
                cwd=core,
                capture_output=True,
                text=True,
            )
            if reverse.returncode != 0:
                raise ValueError(
                    f"test-only correction no longer matches expected source: {name}; manual review required"
                )
            state = "already-present"
        receipts.append(
            {
                "name": name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "state": state,
                "scope": "native test code only; after production install",
            }
        )
    output.write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    prepare(*sys.argv[1:])
