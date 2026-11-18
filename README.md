# Chatmail Dovecot runtime candidates

This repository builds the Lua notification modules omitted from AlmaLinux's
Dovecot packages. The reviewed candidate in `target.env` is
`dovecot-2.3.21-19.el10_2.8`, with the matching signed Alma core and Pigeonhole
packages retained alongside the addon. It preserves the deployed chatmaild 0.2
notification hook. This addon preserves chatmaild 0.2. A separate coherent
upstream 2.4 runtime under `/opt/chatmail-dovecot` provides the full security
migration candidate with matching native Lua modules and a version-specific
relay 1.13 authentication/configuration profile.

The addon now selects a private LMTP module directory instead of overwriting a
library owned by Alma's core RPM. This changes activation and is **not a drop-in
replacement for the historical addon or production updater**. Read
[the assessment and rollout prerequisites](docs/upgrade.md) before promotion.

The full upstream profile, native test corrections, real relay/storage suite,
security evidence linkage and faster 2.4 point-release workflow are documented
in [the private runtime runbook](docs/runtime24.md). Both paths produce
unpromoted candidates; neither activates the production service.

## Build and verify in the project devbox

Use a fresh artifact directory. Build and runtime commands run in rootless
Podman; no production path, account, socket or secret is mounted.

```bash
podman build -t localhost/chatmail-alma-toolchain .
mkdir -p artifacts/candidate
podman run --rm --cpus 8 --memory 12g --pids-limit 1024 \
  -v "$PWD:/project:ro" -v "$PWD/artifacts/candidate:/artifacts" \
  localhost/chatmail-alma-toolchain
podman run --rm --network none -v "$PWD:/project:ro" \
  --entrypoint python3 localhost/chatmail-alma-toolchain \
  -m unittest discover -s /project/tests -p 'test_*.py' -v
podman build --build-arg BASE=localhost/chatmail-alma-toolchain \
  -f Dockerfile.lab -t localhost/chatmail-alma-runtime artifacts/candidate
podman run --rm --network none --cpus 8 --memory 12g --pids-limit 1024 \
  -e CHATMAIL_ISOLATED_LAB=1 \
  -v "$PWD:/project:ro" -v "$PWD/artifacts/candidate:/artifacts" \
  --entrypoint bash localhost/chatmail-alma-runtime /project/scripts/lab-test.sh
```

`scripts/check-target.sh` compares the reviewed pin with current Alma repository
metadata. A newer target requires a reviewed pin change and rebuild; environment
input cannot silently select a different ABI or Dovecot branch.

For faster security intake, `scripts/discover-candidate.sh` reads structured core
and Pigeonhole RPM facts and prepares a separate source workspace with a target
diff and hashed context. Only matching epoch/architecture/source-RPM identities
within Alma's Dovecot 2.3.21 branch are accepted. CI builds that private candidate
and runs the same offline runtime suite. Detection, building, testing and
promotion remain separate receipts; automatic promotion is never performed.

Outputs include signed input/runtime RPMs, the unsigned addon candidate, selected
installed modules, source/configure provenance, a SHA-256 manifest, stage counters
and a failure ledger. The real LMTP suite uses synthetic recipients and a Unix
socket metadata mock; its container has no external network. It checks the Lua
hook, self-message suppression, concurrent user isolation, gzip storage, backend
outage/recovery and unchanged stock library hashes across addon install/removal.
It does not establish real device wakeup, production authentication or rollback.
The current Alma update is an intermediate candidate: the full August 2026
upstream disclosure contains security issues beyond this vendor patch subset.
The downstream relay's runtime security matrix tracks all disclosed CVEs and
keeps missing fixes or applicability evidence unresolved.

CI produces candidate artifacts only. There is no release publisher or tag
trigger: the active legacy production timer consumes the old release namespace.
Publishing there can change production even without SSH access.

## Analysis surfaces

- **Observe:** `build-status.json` counts outcomes at target, source, compile,
  package, runtime and uninstall seams using the existing CI artifact/log surface.
- **Map:** [the service and ownership map](docs/upgrade.md#ownership-and-data-flow)
  connects package selection to the existing notification chain.
- **Audit:** `build-ledger.jsonl`, original/patched specs, input RPMs, toolchain
  inventory and synthetic runtime receipts retain failures and uncertain outcomes.
- **Distribute:** not applicable: this build and hook introduce no probabilistic
  routing. Existing chatmail retry scheduling is preserved outside this addon.

The historical `delta-apply-test.sh` now refuses to install, restart or send mail.
No build script commits, pushes, publishes, enables a service or edits live config.
