#!/usr/bin/env python3
"""Select one installed, relinked module per interface; reject build artifacts."""

import shutil
import subprocess
import sys
from pathlib import Path

FILES = (
    "lib01_mail_lua_plugin.so",
    "lib20_push_notification_plugin.so",
    "lib22_push_notification_lua_plugin.so",
    "libauthdb_lua.so",
    "libdovecot-lua.so.0.0.0",
    "libdovecot-storage-lua.so.0.0.0",
)


def select(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError("artifact destination must be fresh")
    candidates = {}
    for name in FILES:
        matches = [p for p in source.rglob(name) if p.is_file() and not p.is_symlink()]
        if len(matches) != 1:
            raise ValueError(
                f"expected exactly one installed {name}, found {len(matches)}"
            )
        dynamic = subprocess.check_output(["readelf", "-d", str(matches[0])], text=True)
        for line in dynamic.splitlines():
            if "RPATH" in line or "RUNPATH" in line:
                if any(
                    word in line
                    for word in ("/work/", "BUILD", "BUILDROOT", ".libs", "/tmp/")
                ):
                    raise ValueError(f"build path in runtime search path: {name}")
        candidates[name] = matches[0]
    destination.mkdir(parents=True)
    for name, source_file in candidates.items():
        shutil.copy2(source_file, destination / name)


if __name__ == "__main__":
    select(*sys.argv[1:])
