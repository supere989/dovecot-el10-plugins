# Private upstream runtime and future intake

`runtime-target.json` is the owning full-runtime selection. Its reviewed profile
pins official Dovecot and Pigeonhole 2.4.5 archive hashes and the verified primary
signer `EF0882079FD4ED32BF8B23B2A1B09EF84EDC5219`. The independent RPM contains
the full core, Pigeonhole and all native Lua modules under
`/opt/chatmail-dovecot/2.4.5`. It installs no service or production configuration
and replaces no Alma package. The Alma 2.3 addon is a separate intermediate
candidate, with its earlier test evidence preserved.

The native build requires PCRE2 explicitly. Missing regex support previously
compiled an empty implementation while most core tests still passed; the
Pigeonhole CPU-limit fixture exposed that feature gap. The image includes real,
signed EPEL Lua JSON/LPeg packages needed by native HTTP tests. Missing features
or test dependencies are failures, never skipped qualifications.

Production files are installed into the candidate staging tree before two
recorded test-only corrections are applied: the upstream fork-parent pipe fix
and initialization of the process-title API exercised by the logging test.
Tests retain the original nonblocking pipe/backpressure and assertions. Native
suites run as an unprivileged user. Pigeonhole's compiled absolute prefix points
to the staged payload inside the disposable container only. Patch identities,
input signatures, configure logs, native logs and final RPM payload hashes are
preserved. No production C implementation is changed by those test corrections.

RPM's generic RPATH check classifies the intentional absolute `/opt` directory
as invalid. Packaging permits that classification only after a stricter audit
of every ELF dynamic-path component against the one exact private Dovecot
library directory, root ownership, non-writable directory/ELF modes and closed
symlinks. All other RPM RPATH checks remain active. The manifest records the
allowlist and every audited dynamic path; unrelated, relative, empty, stock and
build paths are rejected by contract tests.

## Isolated qualification

Build `Dockerfile`, then `Dockerfile.runtime` using that image as `BASE`. Run the
latter with the repository at `/project:ro`, fresh scratch at `/work`, fresh
output at `/artifacts`, and optional verified cached inputs at `/inputs:ro`
(`UPSTREAM_INPUT_DIR=/inputs`). Limit compilation to eight CPUs and 12 GiB.
No host `/opt`, live mail path, key or socket may be mounted. Cached-input builds
and all real runtime tests use `--network none`.

After native suites and packaging pass, build `Dockerfile.runtime-lab` with the
runtime toolchain as `BASE`. It prepares exact signed/hashed Alma 2.3 controls
and Python dependencies before testing. Run `scripts/lab-runtime24.sh` with the
native source at `/project:ro`, reviewed relay integration source at `/relay:ro`,
artifacts at `/artifacts`, `ARTIFACT_DIR=/artifacts`, and
`CHATMAIL_ISOLATED_LAB=1`. The script installs the dependency-checked private
RPM, verifies installed payload hashes, runs the real protocol suite, removes
the RPM, and checks that Alma's stock push library is unchanged.

The synthetic suite checks actual TLS 1.3 IMAP login, Lua/HTTP provisioning,
wrong passwords and standard-user precedence, concurrent registration, failed
policy/backend reads, LMTP, the deployed notification hook, real metadata and
last-login services, multiple device tokens, durable notification retry,
gzip/quota/message-size policy, bounded LIST/THREAD/compression probes, and
2.3-to-2.4 storage transition. The compression reset check must independently
decompress the second repeated FETCH response; a 2.3 control demonstrates that
the check detects cross-command dictionary reuse. No real device is contacted.

The standard-users policy is root-owned, group `vmail`, mode 0640. The auth
service retains its unprivileged Dovecot user and explicitly uses group `vmail`;
the Lua auth worker runs as `vmail`. Both can read the policy without making
password hashes world-readable. Parent directories must permit traversal to
those identities. Missing, unreadable or malformed policy is an internal auth
failure and must never trigger account provisioning. These are deployment
preconditions, not automatic changes to host accounts or live files.
Independent synthetic authentication cases bind distinct source IPs within
loopback 127/8, so expected wrong-password cases do not accumulate a shared
anti-bruteforce penalty. Production penalty settings remain enabled and
unchanged. No interface configuration or trusted-network bypass is used.

`dovecot_storage_version = 2.4.5` is mandatory to rebuild the old CRC32 thread
index as the keyed v2 representation. The fixture records UIDVALIDITY, UIDs,
flags and message hashes before/after migration. Recovery is tested from a
separate pre-write copy under 2.3 while preserving newly accepted mail in the
new tree. This does **not** qualify downgrading a production mailbox after 2.4
has accepted writes; reconcile new mail and review the storage boundary first.

## Security evidence and promotion

`profiles/security/upstream-2.4.5.json` binds all 25 August disclosure CVEs plus
18 earlier release-history fixes to the exact signed archives. It is explicitly
source disposition data, not a successful build or deployment receipt. The
relay's offline audit combines its pinned data digest with the exact final RPM,
build manifest and real regression receipt. Missing/stale/failed facts, altered
storage policy, wrong source/RPM bytes or incomplete tests remain unknown.
Native/source dispositions have a separate `source_security_qualified` result;
full `security_qualified` also requires the real runtime and storage-transition
receipt, including the active keyed-thread-index format.

Example after actual successful qualification, with the relay CLI installed:

```bash
cmdeploy-runtime-audit --profile upstream-2.4.5-alma10-x86_64 \
  --facts profiles/security/upstream-2.4.5.json \
  --build-manifest artifacts/runtime24/manifest.json \
  --runtime-rpm artifacts/runtime24/rpms/chatmail-dovecot-runtime-2.4.5-1.el10.x86_64.rpm \
  --regression artifacts/runtime24/runtime24-regression.json \
  --output artifacts/runtime24/security-audit.json
```

The package is unsigned and the profile is unpromoted. Full EL10 deployment,
package signing, service/SELinux acceptance, live storage migration, current
backups and exact rollback remain explicit production gates. No candidate
workflow sets them true. The legacy updater remains a publication hazard until
separately migrated; do not publish into its `dovecot-*` release namespace.

## Faster point-release intake

`.github/workflows/runtime24.yml` discovers official stable 2.4 source releases,
verifies detached signatures under the pinned primary key, and prepares a
private source workspace with a profile diff and immutable file-hash context.
Core and Pigeonhole have separately pinned source versions and are compiled
together. A changed key, unsupported branch, source regression or ambiguous
layout fails closed. The owning checkout remains unchanged.
Each component is checked against its own previous version. Older profiles
without a separate Pigeonhole version use the previous core version as its
floor; advancing one component cannot authorize a downgrade of the other.

The workflow builds the selected pair and runs the same native and real
authentication/notification/storage tests. Its configuration and storage policy
remain at the reviewed 2.4.5 baseline. A new source release still requires
review of changed policy, security dispositions and test-only patch state;
version substitution cannot grant promotion.

Cross-repository integration uses a required, exact 40-hex `relay_oid` input or
`CHATMAIL_RUNTIME_RELAY_OID` repository variable. Configure it only after the
reviewed relay integration branch is published. If the OID is absent, native
build evidence is retained,
integration is explicitly unknown, and the workflow fails qualification. There
is no fallback to a branch or to upstream 1.13 sources lacking the new profile.

Receipts distinguish detected, built, tested, promotable and promoted. CI
publishes artifacts/status only. Observe uses existing build counters and job
summaries; Audit retains unknown discoveries, failures and source diffs; Map
connects source evidence → private candidate → native build → real regression →
security audit → explicit promotion. Distribute is not applicable: selection
and bounded retry policy are deterministic.

Draft pull requests skip the candidate jobs, including artifact uploads. Marking
a draft ready for review triggers the normal checks. This keeps draft source
publication separate from candidate-artifact publication.
