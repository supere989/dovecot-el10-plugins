#!/usr/bin/env python3
"""Detect, verify and prepare a private official 2.4 point-release candidate.

No owning checkout edits, release publication, promotion or production calls.
Separate receipts distinguish detection, compilation, qualification and approval.
"""

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from receipt import event
from runtime_profile import load, point, selected
from runtime_profile import validate as validate_profile

ROOTS = {
    "core": "https://dovecot.org/releases/2.4/",
    "pigeonhole": "https://pigeonhole.dovecot.org/releases/2.4/",
}
INPUTS = (
    "scripts",
    "rpm",
    "profiles",
    "patches",
    "tests",
    "examples",
    "docs",
    "target.env",
    "runtime-target.json",
    "Dockerfile",
    "Dockerfile.lab",
    "Dockerfile.runtime",
    "Dockerfile.runtime-lab",
    "README.md",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def newest(index, component):
    stem = "dovecot-" if component == "core" else "dovecot-pigeonhole-"
    versions = set(
        re.findall(r"href=[\"\']" + stem + r"(2\.4\.[0-9]+)\.tar\.gz[\"\']", index)
    )
    supported = [version for version in versions if int(version.rsplit(".", 1)[1]) >= 5]
    if not supported:
        raise ValueError(
            "official stable source discovery is empty; no fallback to stale facts"
        )
    return max(supported, key=point)


def fetch(url, maximum):
    request = urllib.request.Request(
        url, headers={"User-Agent": "chatmail-runtime-intake/1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("official discovery response exceeds its bound")
    return data


def proposed(previous, versions, inputs):
    candidate = dict(previous)
    version = versions["core"]
    previous_versions = {
        "core": previous["version"],
        "pigeonhole": previous.get("pigeonhole_version", previous["version"]),
    }
    for component, previous_version in previous_versions.items():
        if point(versions[component]) < point(previous_version):
            raise ValueError(
                f"release discovery would regress the reviewed {component}"
            )
    candidate.update(
        profile=f"upstream-{version}-alma10-x86_64",
        version=version,
        pigeonhole_version=versions["pigeonhole"],
        prefix=f"/opt/chatmail-dovecot/{version}",
        inputs=inputs,
        promotion=False,
    )
    # Never automatically migrate configuration/storage policy with the source.
    return validate_profile(candidate)


def discover(project, output):
    project, output = Path(project).resolve(), Path(output)
    if output.exists():
        raise ValueError("intake output must be fresh")
    output.mkdir(parents=True)
    _, previous = selected(project)
    versions, inputs = {}, []
    downloaded = output / "verified-downloads"
    downloaded.mkdir()
    for component, base in ROOTS.items():
        index = fetch(base, 2 * 1024 * 1024)
        (output / f"{component}-release-index.html").write_bytes(index)
        version = newest(index.decode("utf-8"), component)
        versions[component] = version
        stem = "dovecot-" if component == "core" else "dovecot-pigeonhole-"
        name = f"{stem}{version}.tar.gz"
        archive = fetch(base + name, 20 * 1024 * 1024)
        (downloaded / name).write_bytes(archive)
        (downloaded / (name + ".sig")).write_bytes(
            fetch(base + name + ".sig", 128 * 1024)
        )
        inputs.append(
            {
                "component": component,
                "name": name,
                "url": base + name,
                "sha256": hashlib.sha256(archive).hexdigest(),
                "size": len(archive),
            }
        )
    (downloaded / "DOVECOT-REPO-GPG-2.4").write_bytes(
        fetch(previous["key_url"], 128 * 1024)
    )
    profile = proposed(previous, versions, inputs)
    candidate_profile = output / "proposed-profile.json"
    candidate_profile.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    # Exact key verification uses the same implementation as the actual build.
    # It extracts only verified archives into this private verification scratch.
    spec = importlib.util.spec_from_file_location(
        "runtime_inputs", project / "scripts/runtime-inputs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = os.environ.get("UPSTREAM_INPUT_DIR")
    os.environ["UPSTREAM_INPUT_DIR"] = str(downloaded.resolve())
    try:
        module.prepare(
            candidate_profile,
            output / "signature-evidence",
            output / "verification-work",
        )
    finally:
        if saved is None:
            os.environ.pop("UPSTREAM_INPUT_DIR", None)
        else:
            os.environ["UPSTREAM_INPUT_DIR"] = saved
    return prepare(project, output / "source", profile)


def prepare(project, destination, profile):
    project, destination = Path(project), Path(destination)
    validate_profile(profile)
    if destination.exists():
        raise ValueError("private candidate workspace already exists")
    original_path, _ = selected(project)
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
        raise ValueError("immutable source revision required")
    destination.mkdir(parents=True)
    for name in INPUTS:
        source = project / name
        if source.is_dir():
            shutil.copytree(
                source,
                destination / name,
                symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            shutil.copy2(source, destination / name, follow_symlinks=False)
    relative = f"profiles/upstream-{profile['version']}.json"
    rendered = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    (destination / relative).write_text(rendered)
    old_target = (project / "runtime-target.json").read_text()
    new_target = (
        json.dumps({"schema_version": 1, "profile_path": relative}, indent=2) + "\n"
    )
    (destination / "runtime-target.json").write_text(new_target)
    diff = "".join(
        difflib.unified_diff(
            original_path.read_text().splitlines(True),
            rendered.splitlines(True),
            fromfile=str(original_path.relative_to(project)),
            tofile=relative,
        )
    )
    diff += "".join(
        difflib.unified_diff(
            old_target.splitlines(True),
            new_target.splitlines(True),
            fromfile="reviewed/runtime-target.json",
            tofile="candidate/runtime-target.json",
        )
    )
    (destination / "target.diff").write_text(diff)
    files = list(destination.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("candidate source may not contain symlinks")
    context = {
        "schema_version": 1,
        "kind": "upstream-runtime",
        "source_revision": revision,
        "profile": profile["profile"],
        "detected": True,
        "built": False,
        "tested": False,
        "promoted": False,
        "policy_review_required": profile["version"] != "2.4.5"
        or profile.get("pigeonhole_version", profile["version"]) != "2.4.5",
        "source_files": {
            str(path.relative_to(destination)): sha(path)
            for path in sorted(files)
            if path.is_file()
        },
    }
    (destination / "candidate-context.json").write_text(
        json.dumps(context, indent=2, sort_keys=True) + "\n"
    )
    return context


def validate(root):
    root = Path(root).resolve()
    context = json.loads((root / "candidate-context.json").read_text())
    _, profile = selected(root)
    if (
        context.get("schema_version") != 1
        or context.get("kind") != "upstream-runtime"
        or context.get("profile") != profile["profile"]
        or context.get("promoted") is not False
        or not re.fullmatch(r"[0-9a-f]{40}", context.get("source_revision", ""))
        or not context.get("source_files")
    ):
        raise ValueError("invalid immutable runtime candidate context")
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
            raise ValueError("candidate input escapes source workspace")
        if sha(path) != expected:
            raise ValueError("candidate source changed after preparation")
    return context["source_revision"]


def receipt(source, artifacts, destination):
    source, artifacts = Path(source), Path(artifacts)
    validate(source)
    context = json.loads((source / "candidate-context.json").read_text())
    manifest = artifacts / "manifest.json"
    regression = artifacts / "runtime24-regression.json"
    built, tested = False, False
    if manifest.exists():
        evidence = json.loads(manifest.read_text())
        built = evidence.get("profile") == context["profile"] and all(
            evidence.get("native_tests", {}).get(name) == "passed"
            for name in ("core", "pigeonhole")
        )
    if built and regression.exists():
        result = json.loads(regression.read_text())
        tested = (
            result.get("passed", 0) > 0
            and not result.get("failed")
            and result.get("build_manifest_sha256") == sha(manifest)
        )
    Path(destination).write_text(
        json.dumps(
            {
                **context,
                "source_files": context["source_files"],
                "built": built,
                "tested": tested,
                "promotable": False,
                "promoted": False,
                "reason": "manual exact-artifact security/configuration/storage review required",
                "build_manifest_sha256": sha(manifest) if manifest.exists() else None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("discover", "validate", "receipt"))
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.action == "discover":
        os.environ["ARTIFACT_DIR"] = str(Path(args.paths[1]).parent)
        event(
            "upstream-discovery",
            "started",
            "official stable core/Pigeonhole sources; pinned signer",
        )
    try:
        result = {"discover": discover, "validate": validate, "receipt": receipt}[
            args.action
        ](*args.paths)
    except Exception as error:
        if args.action == "discover":
            event(
                "upstream-discovery",
                "unknown",
                type(error).__name__ + "; no stale release fallback",
            )
        raise
    if args.action == "discover":
        event(
            "upstream-discovery",
            "ok",
            "signed source pair verified; private candidate prepared; promotion false",
        )
    if result is not None:
        print(result if isinstance(result, str) else json.dumps(result, sort_keys=True))
