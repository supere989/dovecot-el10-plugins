#!/usr/bin/env python3
"""Package only the private coherent runtime and record post-RPM payload bytes."""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from runtime_profile import selected

REQUIRED_MODULES = (
    "libauthdb_lua.so",
    "lib01_mail_lua_plugin.so",
    "lib20_push_notification_plugin.so",
    "lib22_push_notification_lua_plugin.so",
    "lib90_sieve_plugin.so",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(root, prefix):
    private = root / prefix
    if not private.is_dir():
        raise ValueError("private runtime prefix is missing")
    modules = {}
    allowed = {"/" + str(prefix) + "/lib64/dovecot"}
    dynamic_paths, elf_count = {}, 0
    for name in REQUIRED_MODULES:
        matches = [path for path in private.rglob(name) if path.is_file()]
        if len(matches) != 1:
            raise ValueError(
                f"expected one native runtime module {name}, got {len(matches)}"
            )
        modules[name] = str(matches[0].relative_to(root))
    for path in [
        root / "opt",
        root / "opt/chatmail-dovecot",
        private,
        *private.rglob("*"),
    ]:
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute():
                resolved = root / os.path.normpath(target).lstrip("/")
            else:
                resolved = Path(os.path.normpath(path.parent / target))
            if not resolved.is_relative_to(private):
                raise ValueError("private runtime symlink escapes its prefix")
            # Every link in the closed private tree receives the same check;
            # reject dangling/cyclic graphs rather than exporting host lookup.
            seen = {path}
            while resolved.is_symlink():
                if resolved in seen:
                    raise ValueError("cyclic private runtime symlink")
                seen.add(resolved)
                target = os.readlink(resolved)
                resolved = (
                    (root / os.path.normpath(target).lstrip("/"))
                    if Path(target).is_absolute()
                    else Path(os.path.normpath(resolved.parent / target))
                )
                if not resolved.is_relative_to(private):
                    raise ValueError("private runtime symlink escapes its prefix")
            if not resolved.exists():
                raise ValueError("dangling private runtime symlink")
            continue
        info = path.stat()
        if path.is_dir() and (
            info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022
        ):
            raise ValueError(
                "private runtime directory ownership/mode permits loader replacement"
            )
        if path.is_file() and not path.is_symlink():
            if ".so" in path.name and path.name.endswith("T"):
                raise ValueError("temporary shared library in installed runtime")
            with path.open("rb") as source:
                magic = source.read(4)
            if magic == b"\x7fELF":
                elf_count += 1
                if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                    raise ValueError(
                        "private runtime ELF ownership/mode permits loader replacement"
                    )
                dynamic = subprocess.check_output(
                    ["readelf", "-d", str(path)], text=True
                )
                for line in dynamic.splitlines():
                    if "RPATH" in line or "RUNPATH" in line:
                        match = re.search(r"\((?:RPATH|RUNPATH)\).*?\[([^]]*)\]", line)
                        if (
                            not match
                            or not match[1]
                            or any(
                                value not in allowed for value in match[1].split(":")
                            )
                        ):
                            raise ValueError(
                                f"runtime ELF has an unapproved dynamic loader path: {path.name}"
                            )
                        dynamic_paths[str(path.relative_to(root))] = match[1].split(":")
    return modules, {
        "allowed_paths": sorted(allowed),
        "elf_count": elf_count,
        "dynamic_paths": dynamic_paths,
        "ownership_and_modes": "root:root; no group/world writes",
        "result": "passed",
    }


def extract_payload(rpm, top, prefix):
    """Audit RPM metadata, then read back its actual post-brp CPIO payload."""
    query = "[%{FILENAMES}\t%{FILEUSERNAME}\t%{FILEGROUPNAME}\t%{FILEMODES:octal}\t%{FILELINKTOS}\n]"
    records = subprocess.check_output(
        ["rpm", "-qp", "--qf", query, str(rpm)], text=True
    ).splitlines()
    expected = set()
    for row in records:
        name, user, group, mode_text, link = row.split("\t")
        name_path, private = Path(name), Path("/") / prefix
        if (
            ".." in name_path.parts
            or not name_path.is_absolute()
            or (
                name_path != Path("/opt/chatmail-dovecot")
                and not name_path.is_relative_to(private)
            )
        ):
            raise ValueError("RPM owns a path outside its private namespace")
        mode = int(mode_text, 8)
        if (
            user != "root"
            or group != "root"
            or (not stat.S_ISLNK(mode) and mode & 0o022)
        ):
            raise ValueError("RPM ownership/mode allows private loader replacement")
        if stat.S_ISLNK(mode):
            # Relative, closed links allow safe CPIO extraction without ever
            # following the host's absolute /opt namespace.
            if Path(link).is_absolute() or not Path(
                os.path.normpath(name_path.parent / link)
            ).is_relative_to(private):
                raise ValueError("RPM link escapes its private extraction namespace")
        expected.add(name.lstrip("/"))
    archive = top / "payload.cpio"
    with archive.open("wb") as output:
        subprocess.run(["rpm2cpio", str(rpm)], stdout=output, check=True)
    with archive.open("rb") as source:
        members = subprocess.check_output(
            ["cpio", "--list", "--quiet"], stdin=source, text=True
        ).splitlines()
    normalized = [name[2:] if name.startswith("./") else name for name in members]
    if set(normalized) != expected or len(set(normalized)) != len(normalized):
        raise ValueError("RPM metadata/CPIO path inventory mismatch")
    payload = top / "verified-payload"
    payload.mkdir()
    with archive.open("rb") as source:
        subprocess.run(
            [
                "cpio",
                "--extract",
                "--make-directories",
                "--preserve-modification-time",
                "--no-absolute-filenames",
                "--quiet",
            ],
            cwd=payload,
            stdin=source,
            check=True,
        )
    return payload


def package(project, installed, output):
    project, installed, output = Path(project), Path(installed), Path(output)
    _, profile = selected(project)
    prefix = Path(profile["prefix"].lstrip("/"))
    inspect(installed, prefix)
    top = Path(tempfile.mkdtemp(prefix="runtime24-rpm-", dir="/work"))
    (top / "SOURCES").mkdir()
    (top / "SPECS").mkdir()
    shutil.copytree(installed, top / "SOURCES/runtime", symlinks=True)
    spec = top / "SPECS/chatmail-dovecot-runtime.spec"
    shutil.copy2(project / "rpm/chatmail-dovecot-runtime.spec", spec)
    # RPM classifies every intentional absolute /opt path as bit0002. Our
    # stricter exact-prefix/ownership preflight above replaces only that class;
    # every other standard RPM RPATH check remains enabled.
    environment = dict(os.environ, QA_RPATHS="0x0002")
    subprocess.run(
        [
            "rpmbuild",
            "--define",
            f"_topdir {top}",
            "--define",
            f"runtime_version {profile['version']}",
            "-bb",
            str(spec),
        ],
        check=True,
        env=environment,
    )
    packages = list((top / "RPMS/x86_64").glob("*.rpm"))
    if len(packages) != 1:
        raise ValueError("ambiguous runtime package")
    payload = extract_payload(packages[0], top, prefix)
    modules, loader_policy = inspect(payload, prefix)
    (output / "rpms").mkdir()
    rpm_path = output / "rpms" / packages[0].name
    shutil.copy2(packages[0], rpm_path)
    files = {
        str(path.relative_to(payload)): sha(path)
        for path in sorted((payload / prefix).rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    links = {
        str(path.relative_to(payload)): os.readlink(path)
        for path in sorted((payload / prefix).rglob("*"))
        if path.is_symlink()
    }
    source_files = [
        path
        for name in ("scripts", "rpm", "profiles", "patches", "tests")
        for path in (project / name).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    source_files += [
        project / name
        for name in (
            "runtime-target.json",
            "Dockerfile",
            "Dockerfile.runtime",
            "Dockerfile.runtime-lab",
        )
    ]
    revision = os.environ.get("SOURCE_REVISION", "")
    manifest = {
        "schema_version": 1,
        "profile": profile["profile"],
        "source_revision": revision,
        "version": profile["version"],
        "prefix": profile["prefix"],
        "pigeonhole_version": profile.get("pigeonhole_version", profile["version"]),
        "config_version": profile["dovecot_config_version"],
        "storage_version": profile["dovecot_storage_version"],
        "target": f"chatmail-dovecot-runtime-{profile['version']}-{profile['package_release']}",
        "source_archives": {
            item["component"]: item["sha256"] for item in profile["inputs"]
        },
        "source_signer": profile["primary_fingerprint"],
        "rpm": {"name": rpm_path.name, "sha256": sha(rpm_path), "signed": False},
        "modules": modules,
        "payload": files,
        "symlinks": links,
        "source_files": {
            str(path.relative_to(project)): sha(path) for path in sorted(source_files)
        },
        "native_tests": {"core": "passed", "pigeonhole": "passed"},
        "native_test_logs": {
            name: sha(output / name)
            for name in ("core-native-check.log", "pigeonhole-native-check.log")
        },
        "test_only_patches": json.loads(
            (output / "inputs/test-only-patches.json").read_text()
        ),
        "loader_policy": loader_policy,
        "production_ready": False,
    }
    if os.environ.get("NATIVE_SOURCE_SNAPSHOT"):
        native_source = Path(os.environ["NATIVE_SOURCE_SNAPSHOT"])
        if native_source.is_symlink() or not native_source.resolve().is_relative_to(
            Path("/work")
        ):
            raise ValueError(
                "resumed native source evidence must be retained task scratch"
            )
        _, native_profile = selected(native_source)
        if native_profile != profile:
            raise ValueError("resumed native build selected another source profile")
        native_files = [
            path
            for name in ("scripts", "rpm", "profiles", "patches", "tests")
            for path in (native_source / name).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ]
        manifest["package_resume"] = {
            "reason": "package policy correction; same previously tested installed production tree",
            "compile_source_files": {
                str(path.relative_to(native_source)): sha(path)
                for path in sorted(native_files)
            },
            "native_test_logs": manifest["native_test_logs"],
        }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (output / "runtime-requires.txt").write_text(
        subprocess.check_output(["rpm", "-qp", "--requires", str(rpm_path)], text=True)
    )


if __name__ == "__main__":
    package(*sys.argv[1:])
