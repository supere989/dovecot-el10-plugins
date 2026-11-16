#!/usr/bin/env python3
"""Prepare a private same-branch vendor candidate from structured RPM facts.

Never edits the owning checkout or promotes a release. The generated source
workspace has a hashed context, target diff and immutable source revision.
"""

import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

RELEASE = re.compile(r"[1-9][0-9]*\.el10(?:_[0-9]+(?:\.[0-9]+)?)?")
INPUTS = (
    "scripts",
    "rpm",
    "patches",
    "tests",
    "examples",
    "docs",
    "target.env",
    "Dockerfile",
    "Dockerfile.lab",
    "README.md",
)


def candidate_identity(records):
    by_name = {}
    for record in records:
        name = record.get("name")
        if name not in ("dovecot", "dovecot-pigeonhole") or name in by_name:
            raise ValueError("expected one core and one Pigeonhole record")
        if str(record.get("epoch")) != "1" or record.get("arch") != "x86_64":
            raise ValueError("unqualified epoch or architecture")
        if record.get("version") != "2.3.21" or not RELEASE.fullmatch(
            str(record.get("release", ""))
        ):
            raise ValueError(
                "requires a reviewed runtime migration beyond the supported Alma 2.3.21 branch"
            )
        by_name[name] = record
    if set(by_name) != {"dovecot", "dovecot-pigeonhole"}:
        raise ValueError("core/Pigeonhole inventory is incomplete")
    core, sieve = by_name["dovecot"], by_name["dovecot-pigeonhole"]
    for field in ("epoch", "version", "release", "arch", "source_rpm"):
        if core[field] != sieve[field]:
            raise ValueError(f"core/Pigeonhole {field} differs")
    expected_source = f"dovecot-{core['version']}-{core['release']}.src.rpm"
    if core["source_rpm"] != expected_source:
        raise ValueError("source RPM identity differs from the candidate")
    return f"dovecot-{core['version']}-{core['release']}"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(project, destination, records):
    project, destination = Path(project), Path(destination)
    target = candidate_identity(records)
    if destination.exists():
        raise ValueError("candidate source workspace must be fresh")
    revision = subprocess.check_output(
        [
            "git",
            "-c",
            f"safe.directory={project}",
            "-C",
            str(project),
            "rev-parse",
            "HEAD",
        ],
        text=True,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source revision is not an immutable Git object ID")
    destination.mkdir(parents=True)
    for name in INPUTS:
        source, output = project / name, destination / name
        if source.is_dir():
            shutil.copytree(
                source,
                output,
                symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(source, output, follow_symlinks=False)
    original = (project / "target.env").read_text()
    changed, count = re.subn(
        r"^DOVECOT_NVR=.*$", f"DOVECOT_NVR={target}", original, flags=re.M
    )
    if count != 1:
        raise ValueError("owning target file has an ambiguous NVR")
    (destination / "target.env").write_text(changed)
    (destination / "target.diff").write_text(
        "".join(
            difflib.unified_diff(
                original.splitlines(True),
                changed.splitlines(True),
                fromfile="reviewed/target.env",
                tofile="candidate/target.env",
            )
        )
    )
    files = [path for path in destination.rglob("*") if path.is_file()]
    if any(path.is_symlink() for path in destination.rglob("*")):
        raise ValueError("candidate source inputs must not contain symlinks")
    context = {
        "schema_version": 1,
        "source_revision": revision,
        "target_nvr": target,
        "detected": True,
        "built": False,
        "tested": False,
        "promoted": False,
        "rpm_facts": records,
        "source_files": {
            str(path.relative_to(destination)): sha(path) for path in sorted(files)
        },
    }
    (destination / "candidate-context.json").write_text(
        json.dumps(context, indent=2, sort_keys=True) + "\n"
    )
    return context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--assert-nvr", default="")
    args = parser.parse_args()
    facts = [
        json.loads(line)
        for line in Path(args.facts).read_text().splitlines()
        if line.strip()
    ]
    if args.assert_nvr and args.assert_nvr != candidate_identity(facts):
        raise ValueError("requested NVR assertion differs from structured vendor facts")
    print(json.dumps(prepare(args.project, args.destination, facts), sort_keys=True))
