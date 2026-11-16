#!/usr/bin/env python3
"""Enable omitted Lua support without removing any distribution security patch."""

import re
import sys
from pathlib import Path


def prepare(content):
    # The reviewed Alma SRPM builds both core and bundled Pigeonhole. Require
    # that precise two-command layout rather than patching arbitrary matches.
    commands = list(
        re.finditer(r"^\s*(?:%configure|\./configure)(?=\s|\\|$)", content, re.M)
    )
    if len(commands) != 2:
        raise ValueError(
            f"expected core and Pigeonhole configure commands, found {len(commands)}"
        )
    core = content[commands[0].start() : commands[1].start()]
    pigeonhole = content[commands[1].start() :]
    if (
        "--with-systemd" not in core
        or "pushd dovecot-pigeonhole" not in core
        or "--with-dovecot=../" not in pigeonhole
    ):
        raise ValueError("unrecognized core/Pigeonhole configure layout")
    core = re.sub(
        r"--without-lua\b|--with-lua(?:=[^\s\\]+)?", "--with-lua=plugin", core
    )
    core = re.sub(
        r"^(\s*(?:%configure|\./configure))(?=\s|\\|$)",
        r"\1 --with-lua=plugin --disable-rpath",
        core,
        count=1,
        flags=re.M,
    )
    # Lua development dependencies are installed explicitly by the toolchain;
    # record them in the patched spec as well for builddep/provenance.
    return (
        "BuildRequires: lua-devel\n"
        + content[: commands[0].start()]
        + core
        + pigeonhole
    )


if __name__ == "__main__":
    source, target = map(Path, sys.argv[1:])
    target.write_text(prepare(source.read_text()))
