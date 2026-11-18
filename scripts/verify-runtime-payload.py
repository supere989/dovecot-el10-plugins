"""Read back exact candidate RPM/payload; never install or activate it."""

import hashlib
import json
import os
import sys
from pathlib import Path

from runtime_profile import point


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(action, artifacts):
    artifacts = Path(artifacts)
    manifest = json.loads((artifacts / "manifest.json").read_text())
    point(manifest["version"])
    prefix = Path(f"/opt/chatmail-dovecot/{manifest['version']}")
    if manifest.get("prefix") != str(prefix):
        raise ValueError("invalid private payload prefix")
    name = manifest["rpm"]["name"]
    if Path(name).name != name or not name.endswith(".rpm"):
        raise ValueError("invalid candidate RPM name")
    rpm = artifacts / "rpms" / name
    if rpm.is_symlink() or digest(rpm) != manifest["rpm"]["sha256"]:
        raise ValueError("candidate RPM differs from manifest")
    if action == "select":
        return str(rpm)
    if action != "installed":
        raise ValueError("unknown payload check")
    for path in (Path("/opt"), Path("/opt/chatmail-dovecot"), prefix):
        info = path.stat()
        if (
            path.is_symlink()
            or info.st_uid != 0
            or info.st_gid != 0
            or info.st_mode & 0o022
        ):
            raise ValueError(
                "installed private loader directory ownership/mode is unsafe"
            )
    for relative, expected in manifest["payload"].items():
        path = Path("/") / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not path.is_relative_to(prefix)
            or path.is_symlink()
        ):
            raise ValueError("manifest payload escapes the private runtime")
        if digest(path) != expected:
            raise ValueError("installed runtime byte mismatch")
    for relative, expected in manifest.get("symlinks", {}).items():
        path = Path("/") / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not path.is_relative_to(prefix)
            or not path.is_symlink()
            or os.readlink(path) != expected
        ):
            raise ValueError("installed runtime symlink mismatch")


if __name__ == "__main__":
    result = verify(*sys.argv[1:])
    if result:
        print(result)
