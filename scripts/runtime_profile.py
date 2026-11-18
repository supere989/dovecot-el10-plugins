"""One fail-closed interface for reviewed and private 2.4 point candidates.

The configuration/storage baseline is deliberately independent of a new source
version. Intake may build a point release; it cannot approve a policy migration.
"""

import json
import re
import sys
from pathlib import Path

PRIMARY = "EF0882079FD4ED32BF8B23B2A1B09EF84EDC5219"
KEY_URL = "https://dovecot.org/gpgkeys/DOVECOT-REPO-GPG-2.4"
BASELINE = "2.4.5"


def point(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"2\.4\.(?:[5-9]|[1-9][0-9]+)", value
    ):
        raise ValueError(
            "only stable 2.4 point releases at or after 2.4.5 are supported; migration review required"
        )
    return tuple(map(int, value.split(".")))


def validate(profile):
    version = profile.get("version")
    point(version)
    sieve = profile.get("pigeonhole_version", version)
    point(sieve)
    if (
        profile.get("schema_version") != 1
        or profile.get("architecture") != "x86_64"
        or profile.get("profile") != f"upstream-{version}-alma10-x86_64"
        or profile.get("prefix") != f"/opt/chatmail-dovecot/{version}"
        or profile.get("package_name") != "chatmail-dovecot-runtime"
        or profile.get("package_release") != "1.el10"
        or profile.get("primary_fingerprint") != PRIMARY
        or profile.get("key_url") != KEY_URL
        or profile.get("dovecot_config_version") != BASELINE
        or profile.get("dovecot_storage_version") != BASELINE
        or profile.get("promotion") is not False
    ):
        raise ValueError(
            "runtime profile differs from the reviewed signer, layout or configuration/storage policy"
        )
    inputs = profile.get("inputs", [])
    if len(inputs) != 2 or {item.get("component") for item in inputs} != {
        "core",
        "pigeonhole",
    }:
        raise ValueError("exactly one core/Pigeonhole source pair is required")
    for item in inputs:
        core = item["component"] == "core"
        name = (
            f"dovecot-{version}.tar.gz"
            if core
            else f"dovecot-pigeonhole-{sieve}.tar.gz"
        )
        base = (
            "https://dovecot.org/releases/2.4/"
            if core
            else "https://pigeonhole.dovecot.org/releases/2.4/"
        )
        if (
            item.get("name") != name
            or item.get("url") != base + name
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
            or type(item.get("size")) is not int
            or not 0 < item["size"] <= 20 * 1024 * 1024
        ):
            raise ValueError("invalid official runtime input identity")
    return profile


def load(path):
    return validate(json.loads(Path(path).read_text()))


def selected(project):
    project = Path(project).resolve()
    target = json.loads((project / "runtime-target.json").read_text())
    name = target.get("profile_path", "")
    if target.get("schema_version") != 1 or not re.fullmatch(
        r"profiles/upstream-2\.4\.[0-9]+\.json", name
    ):
        raise ValueError("invalid owning runtime target")
    path = project / name
    if path.is_symlink() or not path.resolve().is_relative_to(project):
        raise ValueError("runtime profile escapes the source workspace")
    return path, load(path)


if __name__ == "__main__":
    path, profile = selected(sys.argv[1])
    print(path)
    for field in ("prefix", "version"):
        print(profile[field])
    print(profile.get("pigeonhole_version", profile["version"]))
