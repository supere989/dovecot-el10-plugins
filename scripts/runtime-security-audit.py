"""Run the relay's pure checker on this exact candidate; never invent new fixes."""

import hashlib
import json
import os
import sys
from pathlib import Path

from runtime_profile import selected


def main(project, artifacts):
    project, artifacts = Path(project), Path(artifacts)
    sys.path.insert(
        0, str(Path(os.environ.get("RELAY_SOURCE", "/relay")) / "cmdeploy/src")
    )
    from cmdeploy.runtime_bundle import verify
    from cmdeploy.runtime_security import check, load_lock

    lock = load_lock()
    _, profile = selected(project)
    source = project / "profiles/security/upstream-2.4.5.json"
    facts = json.loads(source.read_text())
    facts["_file_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    identifier = profile["profile"]
    if identifier not in lock["profiles"]:
        result = {
            "profile": identifier,
            "security_qualified": False,
            "deployable": False,
            "security_counts": {
                "fixed": 0,
                "not-applicable": 0,
                "affected": 0,
                "unknown": len(facts["inventory"]["required_ids"]),
            },
            "unresolved": [
                "new source pair requires reviewed security/configuration/storage classification; prior release dispositions are not inherited"
            ],
        }
    else:
        manifest = json.loads((artifacts / "manifest.json").read_text())
        facts["build_evidence"] = verify(
            lock["profiles"][identifier],
            artifacts / "manifest.json",
            artifacts / "rpms" / manifest["rpm"]["name"],
            artifacts / "runtime24-regression.json",
        )
        result = check(lock, identifier, facts)
    (artifacts / "security-audit.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "profile": identifier,
                "security_counts": result["security_counts"],
                "security_qualified": result["security_qualified"],
                "deployable": result["deployable"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main(*sys.argv[1:])
