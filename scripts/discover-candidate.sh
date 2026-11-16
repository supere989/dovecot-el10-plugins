#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
CURRENT_STAGE=discovery
dnf -q --refresh repoquery --latest-limit=1 --archlist=x86_64 \
  --qf '{"name":"%{name}","epoch":"%{epoch}","version":"%{version}","release":"%{release}","arch":"%{arch}","source_rpm":"%{sourcerpm}"}' \
  dovecot dovecot-pigeonhole > "${ARTIFACT_DIR}/rpm-facts.jsonl"
python3 "${PROJECT_DIR}/scripts/prepare-candidate.py" --project "${PROJECT_DIR}" \
  --facts "${ARTIFACT_DIR}/rpm-facts.jsonl" --destination "${ARTIFACT_DIR}/source" \
  --assert-nvr "${DOVECOT_NVR_ASSERTION:-}"
stage discovery ok 'private same-branch candidate prepared; unbuilt and unpromoted'
