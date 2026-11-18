import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def package_module():
    spec = importlib.util.spec_from_file_location(
        "package_runtime", ROOT / "scripts/package-runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateLoader(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.module = package_module()
        self.prefix = Path("opt/chatmail-dovecot/2.4.5")
        self.private = self.root / self.prefix
        self.private.mkdir(parents=True)
        for name in self.module.REQUIRED_MODULES:
            (self.private / name).write_bytes(b"\x7fELFsynthetic")
        self.dynamic = (
            "(RPATH) Library rpath: [/opt/chatmail-dovecot/2.4.5/lib64/dovecot]"
        )

    def tearDown(self):
        self.scratch.cleanup()

    def inspect(self, dynamic=None):
        with patch.object(
            self.module.subprocess,
            "check_output",
            return_value=self.dynamic if dynamic is None else dynamic,
        ):
            return self.module.inspect(self.root, self.prefix)

    def test_exact_private_rpath_and_regular_owner_modes_are_recorded(self):
        modules, policy = self.inspect()
        self.assertEqual(len(modules), 5)
        self.assertEqual(policy["elf_count"], 5)
        self.assertEqual(
            policy["allowed_paths"], ["/opt/chatmail-dovecot/2.4.5/lib64/dovecot"]
        )

    def test_build_stock_empty_relative_and_other_private_paths_are_rejected(self):
        for path in (
            "/work/build/.libs",
            "/usr/lib64/dovecot",
            "",
            "../lib",
            "$ORIGIN",
            "/tmp/library",
            "/opt/chatmail-dovecot/2.4.6/lib64/dovecot",
            "/opt/chatmail-dovecot/2.4.5/lib64/dovecot:",
        ):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ValueError, "dynamic loader path"),
            ):
                self.inspect(f"(RUNPATH) Library runpath: [{path}]")

    def test_writable_directory_and_elf_are_rejected(self):
        self.private.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "directory ownership/mode"):
            self.inspect()
        self.private.chmod(0o755)
        (self.private / self.module.REQUIRED_MODULES[0]).chmod(0o666)
        with self.assertRaisesRegex(ValueError, "ELF ownership/mode"):
            self.inspect()

    def test_symlink_escape_and_cycle_are_rejected(self):
        link = self.private / "bad.so"
        for target in (
            "/usr/lib64/libc.so.6",
            "/opt/chatmail-dovecot/2.4.5/../../escape",
            "../../escape",
        ):
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink escapes"):
                self.inspect()
            link.unlink()
        link.symlink_to("bad.so")
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.inspect()

    def test_unsafe_rpm_metadata_is_rejected_before_extraction(self):
        records = (
            "/etc/passwd\troot\troot\t100644\t\n",
            "/opt/chatmail-dovecot/2.4.5/library\tnobody\troot\t100644\t\n",
            "/opt/chatmail-dovecot/2.4.5/library\troot\troot\t100666\t\n",
            "/opt/chatmail-dovecot/2.4.5/library\troot\troot\t120777\t/usr/lib64/libc.so.6\n",
        )
        for record in records:
            with (
                self.subTest(record=record),
                patch.object(
                    self.module.subprocess, "check_output", return_value=record
                ),
                patch.object(self.module.subprocess, "run") as execute,
            ):
                with self.assertRaises(ValueError):
                    self.module.extract_payload(
                        self.root / "candidate.rpm", self.root, self.prefix
                    )
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
