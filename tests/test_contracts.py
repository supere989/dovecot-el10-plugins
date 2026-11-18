import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    return instance


class Contracts(unittest.TestCase):
    def test_spec_patch_keeps_security_patches_and_other_flags(self):
        original = "\n".join(
            (
                "Name: dovecot",
                "Patch1: security.patch",
                "%prep",
                "%autosetup -p1",
                "%build",
                "%configure --with-systemd --with-pam \\",
                "  --without-lua",
                "",
                "pushd dovecot-pigeonhole",
                "%configure --with-dovecot=../",
                "",
            )
        )
        changed = module("prepare-spec").prepare(original)
        self.assertEqual(changed.count("%configure"), 2)
        self.assertIn("%configure --with-dovecot=../", changed)
        self.assertIn("Patch1: security.patch", changed)
        self.assertIn("%autosetup -p1", changed)
        self.assertIn("--with-pam", changed)
        self.assertIn("--with-lua=plugin --disable-rpath", changed)
        self.assertNotIn("--without-lua", changed)

    def test_ambiguous_configure_fails(self):
        with self.assertRaises(ValueError):
            module("prepare-spec").prepare("%configure\n./configure\n")

    def test_unknown_configure_fails(self):
        with self.assertRaises(ValueError):
            module("prepare-spec").prepare("%build\nmake\n")

    def test_changed_pigeonhole_marker_fails(self):
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            module("prepare-spec").prepare(
                "%configure --with-systemd\npushd dovecot-pigeonhole\n%configure --with-dovecot=/different\n"
            )

    def test_duplicate_core_layout_fails(self):
        with self.assertRaises(ValueError):
            module("prepare-spec").prepare(
                "%configure --with-systemd\n%configure --with-systemd\n"
            )

    def test_target_rejects_different_release_and_ledgers_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(
                os.environ, ARTIFACT_DIR=temporary, DOVECOT_NVR="dovecot-2.4.5-1.el10"
            )
            result = subprocess.run(
                ["bash", "-c", 'source "$1"', "test", str(ROOT / "scripts/common.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            ledger = [
                json.loads(line)
                for line in (Path(temporary) / "build-ledger.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(ledger[-1]["result"], "rejected")

    def test_target_rejects_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                ["bash", "-c", 'source "$1"', "test", str(ROOT / "scripts/common.sh")],
                env=dict(os.environ, ARTIFACT_DIR=temporary, TARGET_ARCH="aarch64"),
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)

    def test_installed_artifacts_reject_duplicate(self):
        selector = module("select-artifacts")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one").mkdir()
            (root / "two").mkdir()
            for directory in ("one", "two"):
                (root / directory / selector.FILES[0]).write_bytes(b"duplicate")
            with self.assertRaisesRegex(ValueError, "found 2"):
                selector.select(root, root / "out")

    def test_artifacts_exclude_temporary_libraries(self):
        selector = module("select-artifacts")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in selector.FILES:
                (root / name).write_bytes(b"synthetic")
            (root / "libdovecot-lua.so.0.0.0T").write_bytes(b"temporary")
            with patch.object(selector.subprocess, "check_output", return_value=""):
                selector.select(root, root / "out")
            self.assertEqual(
                {p.name for p in (root / "out").iterdir()}, set(selector.FILES)
            )

    def test_build_rpath_is_rejected(self):
        selector = module("select-artifacts")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in selector.FILES:
                (root / name).write_bytes(b"synthetic")
            with patch.object(
                selector.subprocess,
                "check_output",
                return_value="(RPATH) Library rpath: [/work/BUILD/.libs]",
            ):
                with self.assertRaisesRegex(ValueError, "build path"):
                    selector.select(root, root / "out")

    def test_unsafe_legacy_entrypoint_refuses(self):
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/delta-apply-test.sh")], capture_output=True
        )
        self.assertEqual(result.returncode, 2)

    def test_installed_relink_receives_exact_rpm_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_make, record = root / "make", root / "command.txt"
            fake_make.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$RPM_PACKAGE_NAME" "$RPM_PACKAGE_VERSION" "$RPM_PACKAGE_RELEASE" "$RPM_ARCH" "$@" > "$TEST_RECORD"\n'
            )
            fake_make.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/install-tree.sh"),
                    "/prepared tree",
                    "/staged tree",
                ],
                env=dict(
                    os.environ,
                    PATH=f"{root}:{os.environ['PATH']}",
                    TEST_RECORD=str(record),
                    ARTIFACT_DIR=str(root / "evidence"),
                ),
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                record.read_text().splitlines(),
                [
                    "dovecot",
                    "2.3.21",
                    "19.el10_2.8",
                    "x86_64",
                    "-C",
                    "/prepared tree",
                    "install",
                    "DESTDIR=/staged tree",
                    "-j8",
                ],
            )

    def test_rpm_does_not_overwrite_or_run_scriptlets(self):
        spec = (ROOT / "rpm/SPECS/dovecot-el10-lua-plugins.spec").read_text()
        self.assertNotIn("%post", spec)
        self.assertNotIn("%preun", spec)
        self.assertIn("Requires:       dovecot(x86-64) =", spec)


if __name__ == "__main__":
    unittest.main()
