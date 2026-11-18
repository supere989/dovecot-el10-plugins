#!/usr/bin/env python3
"""Verify official signed archives and safely prepare a coherent source pair."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from runtime_profile import load


def obtain(url, output, cached=None, maximum=20 * 1024 * 1024):
    if cached is not None and cached.exists():
        shutil.copyfile(cached, output)
        return
    request = urllib.request.Request(
        url, headers={"User-Agent": "chatmail-runtime-build/1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("official input exceeds the download bound")
    output.write_bytes(content)


def prepare(profile_path, inputs_dir, build_dir):
    profile = load(profile_path)
    inputs_dir, build_dir = Path(inputs_dir), Path(build_dir)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    cache = (
        Path(os.environ["UPSTREAM_INPUT_DIR"])
        if os.environ.get("UPSTREAM_INPUT_DIR")
        else None
    )
    key = inputs_dir / "DOVECOT-REPO-GPG-2.4"
    obtain(
        profile["key_url"], key, cache / key.name if cache else None, maximum=128 * 1024
    )
    keyring = build_dir / "public-keyring"
    keyring.mkdir(mode=0o700)
    subprocess.run(
        ["gpg", "--batch", "--homedir", str(keyring), "--import", str(key)], check=True
    )
    receipts = []
    if {item.get("component") for item in profile["inputs"]} != {
        "core",
        "pigeonhole",
    } or len(profile["inputs"]) != 2:
        raise ValueError("expected exactly one core/Pigeonhole source pair")
    for item in profile["inputs"]:
        name = item["name"]
        expected = (
            f"dovecot-{profile['version']}.tar.gz"
            if item["component"] == "core"
            else f"dovecot-pigeonhole-{profile.get('pigeonhole_version', profile['version'])}.tar.gz"
        )
        if name != expected or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("source name/digest differs from its component")
        archive, signature = inputs_dir / name, inputs_dir / f"{name}.sig"
        obtain(item["url"], archive, cache / name if cache else None)
        obtain(
            item["url"] + ".sig",
            signature,
            cache / signature.name if cache else None,
            maximum=128 * 1024,
        )
        if (
            archive.stat().st_size != item["size"]
            or hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("source archive size/digest mismatch")
        status = subprocess.run(
            [
                "gpg",
                "--batch",
                "--homedir",
                str(keyring),
                "--status-fd=1",
                "--verify",
                str(signature),
                str(archive),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        valid = [
            line.split()[2:]
            for line in status.stdout.splitlines()
            if line.startswith("[GNUPG:] VALIDSIG ")
        ]
        if not any(
            fields
            and (
                fields[0] == profile["primary_fingerprint"]
                or fields[-1] == profile["primary_fingerprint"]
            )
            for fields in valid
        ):
            raise ValueError(
                "signature primary fingerprint differs from the reviewed signer"
            )
        (inputs_dir / f"{item['component']}.signature-status.txt").write_text(
            status.stdout
        )
        source_root = name.removesuffix(".tar.gz")
        with tarfile.open(archive) as source:
            if any(
                not member.name.startswith(source_root + "/")
                and member.name != source_root
                for member in source.getmembers()
            ):
                raise ValueError("source archive has an unexpected top-level path")
            source.extractall(build_dir, filter="data")
        receipts.append(
            dict(
                component=item["component"],
                sha256=item["sha256"],
                signature_verified=True,
                primary_fingerprint=profile["primary_fingerprint"],
                source_root=str(build_dir / source_root),
            )
        )
    (inputs_dir / "verified-inputs.json").write_text(
        json.dumps(receipts, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    prepare(*sys.argv[1:])
