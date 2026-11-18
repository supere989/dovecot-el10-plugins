import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def facts(release="19.el10_2.8"):
    return [
        dict(
            name=name,
            epoch="1",
            version="2.3.21",
            release=release,
            arch="x86_64",
            source_rpm=f"dovecot-2.3.21-{release}.src.rpm",
        )
        for name in ("dovecot", "dovecot-pigeonhole")
    ]


class Intake(unittest.TestCase):
    def test_next_same_branch_vendor_candidate_is_supported(self):
        self.assertEqual(
            load("prepare-candidate").candidate_identity(facts("20.el10_3.1")),
            "dovecot-2.3.21-20.el10_3.1",
        )

    def test_core_pigeonhole_mismatch_is_rejected(self):
        records = facts()
        records[1]["release"] = "19.el10_2.1"
        with self.assertRaises(ValueError):
            load("prepare-candidate").candidate_identity(records)

    def test_unsupported_major_requires_migration(self):
        records = facts()
        for record in records:
            record["version"] = "2.4.5"
        with self.assertRaisesRegex(ValueError, "migration"):
            load("prepare-candidate").candidate_identity(records)

    def test_missing_duplicate_and_wrong_arch_are_rejected(self):
        for records in (facts()[:1], facts() + facts()[:1]):
            with self.assertRaises(ValueError):
                load("prepare-candidate").candidate_identity(records)
        records = facts()
        records[0]["arch"] = "aarch64"
        with self.assertRaises(ValueError):
            load("prepare-candidate").candidate_identity(records)

    def test_source_identity_must_match_both_binary_records(self):
        records = facts()
        for record in records:
            record["source_rpm"] = "dovecot-2.3.21-16.el10.src.rpm"
        with self.assertRaisesRegex(ValueError, "source RPM"):
            load("prepare-candidate").candidate_identity(records)

    def test_generated_workspace_is_private_hashed_and_unpromoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate"
            context = load("prepare-candidate").prepare(
                ROOT, output, facts("20.el10_3.1")
            )
            revision = load("read-candidate-context").validate(
                output, context["target_nvr"]
            )
            self.assertEqual(revision, context["source_revision"])
            self.assertFalse(
                context["built"] or context["tested"] or context["promoted"]
            )
            self.assertIn("20.el10_3.1", (output / "target.diff").read_text())
            self.assertIn("19.el10_2.8", (ROOT / "target.env").read_text())
            (output / "scripts/common.sh").write_text("edited after detection")
            with self.assertRaisesRegex(ValueError, "edited"):
                load("read-candidate-context").validate(output, context["target_nvr"])


if __name__ == "__main__":
    unittest.main()
