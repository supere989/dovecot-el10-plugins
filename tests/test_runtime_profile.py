import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime_profile import selected, validate


def intake():
    spec = importlib.util.spec_from_file_location(
        "upstream_candidate", ROOT / "scripts/upstream-candidate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources_for(profile, versions):
    inputs = copy.deepcopy(profile["inputs"])
    for source in inputs:
        component = source["component"]
        stem = "dovecot-" if component == "core" else "dovecot-pigeonhole-"
        name = f"{stem}{versions[component]}.tar.gz"
        source.update(name=name, url=intake().ROOTS[component] + name)
    return inputs


class RuntimeProfile(unittest.TestCase):
    def test_reviewed_target_and_storage_baseline(self):
        _, profile = selected(ROOT)
        self.assertEqual(validate(profile)["dovecot_storage_version"], "2.4.5")

    def test_major_signer_url_storage_and_prefix_drift_are_rejected(self):
        _, original = selected(ROOT)
        for key, value in (
            ("version", "2.5.0"),
            ("primary_fingerprint", "A" * 40),
            ("prefix", "/usr"),
            ("dovecot_storage_version", "2.4.0"),
            ("key_url", "https://example.test/key"),
            ("promotion", True),
        ):
            profile = copy.deepcopy(original)
            profile[key] = value
            with self.assertRaises(ValueError):
                validate(profile)

    def test_stable_official_index_ignores_prerelease_and_old_versions(self):
        html = '<a href="dovecot-2.4.0.tar.gz">old</a><a href="dovecot-2.4.6.tar.gz">new</a><a href="dovecot-2.4.7.rc1.tar.gz">rc</a>'
        self.assertEqual(intake().newest(html, "core"), "2.4.6")
        with self.assertRaises(ValueError):
            intake().newest('<a href="dovecot-2.5.0.tar.gz">migration</a>', "core")

    def test_each_component_downgrade_is_rejected(self):
        _, original = selected(ROOT)
        versions = {"core": "2.4.6", "pigeonhole": "2.4.6"}
        previous = intake().proposed(
            original, versions, sources_for(original, versions)
        )
        for core, pigeonhole, component in (
            ("2.4.5", "2.4.6", "core"),
            ("2.4.6", "2.4.5", "pigeonhole"),
            ("2.4.7", "2.4.5", "pigeonhole"),
        ):
            with self.subTest(core=core, pigeonhole=pigeonhole):
                versions = {"core": core, "pigeonhole": pigeonhole}
                with self.assertRaisesRegex(ValueError, f"regress.*{component}"):
                    intake().proposed(
                        previous, versions, sources_for(previous, versions)
                    )

    def test_previous_pigeonhole_version_defaults_to_core_version(self):
        _, original = selected(ROOT)
        versions = {"core": "2.4.6", "pigeonhole": "2.4.6"}
        previous = intake().proposed(
            original, versions, sources_for(original, versions)
        )
        previous.pop("pigeonhole_version")
        validate(previous)
        versions = {"core": "2.4.7", "pigeonhole": "2.4.5"}
        with self.assertRaisesRegex(ValueError, "regress.*pigeonhole"):
            intake().proposed(previous, versions, sources_for(previous, versions))

    def test_pigeonhole_can_advance_independently(self):
        _, previous = selected(ROOT)
        versions = {"core": "2.4.5", "pigeonhole": "2.4.6"}
        candidate = intake().proposed(
            previous, versions, sources_for(previous, versions)
        )
        self.assertEqual(candidate["version"], "2.4.5")
        self.assertEqual(candidate["pigeonhole_version"], "2.4.6")
        self.assertEqual(candidate["dovecot_storage_version"], "2.4.5")

    def test_new_candidate_keeps_config_policy_and_immutable_inputs(self):
        _, profile = selected(ROOT)
        profile = copy.deepcopy(profile)
        versions = {"core": "2.4.6", "pigeonhole": "2.4.5"}
        inputs = copy.deepcopy(profile["inputs"])
        inputs[0].update(
            name="dovecot-2.4.6.tar.gz",
            url="https://dovecot.org/releases/2.4/dovecot-2.4.6.tar.gz",
        )
        candidate = intake().proposed(profile, versions, inputs)
        self.assertEqual(candidate["dovecot_storage_version"], "2.4.5")
        self.assertEqual(candidate["pigeonhole_version"], "2.4.5")
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "source"
            context = intake().prepare(ROOT, destination, candidate)
            self.assertTrue(context["policy_review_required"])
            self.assertFalse(
                context["built"] or context["tested"] or context["promoted"]
            )
            self.assertEqual(intake().validate(destination), context["source_revision"])
            self.assertEqual(
                json.loads((ROOT / "runtime-target.json").read_text())["profile_path"],
                "profiles/upstream-2.4.5.json",
            )
            (destination / "unexpected.py").write_text("additional untracked source")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                intake().validate(destination)
            (destination / "unexpected.py").unlink()
            (destination / "scripts/build-runtime.sh").write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                intake().validate(destination)


if __name__ == "__main__":
    unittest.main()
