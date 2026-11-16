# Validation receipt — November 16, 2026

All execution used task-specific rootless containers. Production services,
mailboxes, configuration, secrets, timers and unrelated workloads were not
changed. Qualification produced no commit, push, tag, release or real message;
source publication is a separately reviewed step.

The feature-complete upstream 2.4.5 core/Pigeonhole/Lua build requires PCRE2 and
passed 162/162 core Automake programs and 651 Pigeonhole svtests across 133
groups. Source inputs and signatures are retained in
`artifacts-backups/upstream-2.4.5-inputs`; source/build/native-test evidence is
under `artifacts/runtime24-run2`. Earlier incomplete or failed runs remain
separate and are not counted as qualification.

The final formatted packaging recipe resumed the same tested installed tree;
it did not recompile production C. It audited the RPM namespace, root ownership,
non-writable directory/ELF modes, closed links and every ELF loader path, then
hashed the actual extracted post-RPM payload. The manifest records original
native source snapshot hashes, native test log hashes and final packaging
source hashes separately.

The exact-artifact offline security audit reports 43/43 fixed dispositions:
all 25 August CSAF CVEs plus 18 earlier release-history fixes, bound to the
reviewed signed source archives, final RPM and successful real runtime/storage
receipt. `source_security_qualified`, `runtime_qualified` and
`security_qualified` are true; `deployable` remains false. This is the stated
disclosure inventory, not an exhaustive historical CVE catalog. Its report is
`artifacts/runtime24-lab6/security-audit.json`.

- RPM: `chatmail-dovecot-runtime-2.4.5-1.el10.x86_64.rpm`
- RPM SHA-256: `e7e21ed10e1ddab8b681d641f065c18851cff6f2b292a216b557fa342659bf2d`
- Build manifest SHA-256: `93ead3db14942a7a47bb32b90ad790b72066d4d6d3a2ba72e97e00dd11f1e2f7`
- Package evidence: `artifacts/runtime24-package5`

The actual RPM passed the complete offline real-protocol suite, exit 0, in
`artifacts/runtime24-lab6`: 20 checks, plus dependency-checked package install,
installed-payload readback, uninstall and unchanged stock push-library hashes.
The receipt binds the exact manifest above, relay base OID
`4ffb501c5e15e4c2d9a801f4baff1d214ce1fbed`, and actual executed relay profile/service
file hashes. That base OID alone does not describe the uncommitted integration
changes; the file hashes are required evidence.

The suite covers correct/wrong/foreign/static-user authentication, Lua/HTTP
provisioning and races, missing/unreadable/malformed policy refusal, bounded
backend outage, real metadata and notifier retry, multiple devices, self-message
suppression, concurrent mailbox isolation, last-login timestamps, quota/gzip and
oversize rejection with no delivery. It preserves UIDVALIDITY, UIDs, persistent
flags and bytes across a real 2.3-to-2.4 transition and proves thread-index v1-to-v2
rebuild. The compression-reset check independently decodes a repeated FETCH
response and is sensitive against a real 2.3 control.

The separate pre-write recovery copy worked under 2.3 and did not rewind newly
accepted messages in the new tree. Downgrading the post-write 2.4 tree is not
qualified. Production migration needs a current recovery plan and reconciliation
boundary, plus package signing, explicit promotion, service/SELinux acceptance
and legacy-updater migration.

Guard-reported repository checks: 31 native contract/intake/loader tests and 59
focused relay runtime/security/preflight/deployer tests pass. Scoped Ruff format
and import checks pass. An earlier broader inherited host Ruff profile reported 31 optional
style diagnostics; the native repository has no owning Ruff configuration or
CI gate for those rules, and this is not reported as a full Ruff pass. Python
helpers are invoked explicitly with `python3`. Intentional nonzero subprocess
probes inspect return codes; verification/build/extraction operations require
success.

The first staged adversarial review found that future intake checked core
rollback but not an independent Pigeonhole rollback. Both components now have
their own version floor; legacy profiles without a Pigeonhole version use the
previous core version. The 31-test run includes both downgrade directions,
the legacy fallback and independent component advancement. This selection-only
correction does not change the qualified 2.4.5 RPM or its exact receipts above.

Actual official release discovery succeeded in `artifacts/upstream-intake1`:
both current stable sources were 2.4.5, the pinned primary signer verified, and a
private hashed candidate source workspace and diff were generated. That intake
receipt truthfully remains detected=true, built=false, tested=false,
promoted=false. The full owning-profile build/runtime evidence above is
separate. Scheduled cross-repository CI requires publication/configuration of
an explicitly reviewed relay integration OID; no publication was performed.

SAI evidence is separate for each function. Observe uses existing JSON counters,
job summaries and explicit exit results at source/build/package/runtime seams.
Map connects primary facts → reviewed profile → native package → real relay
regression → security audit → explicit promotion in `runtime24.md` and the relay
overview. Audit retains all numbered failures, unknown discovery outcomes,
source diffs and unresolved production contracts. Distribute is not applicable:
this deterministic intake/build path adds no probabilistic choice.
