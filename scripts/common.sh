#!/usr/bin/env bash
# Shared, fail-closed candidate identity and the existing build artifact surface.
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REQUESTED_NVR=${DOVECOT_NVR-}
REQUESTED_ARCH=${TARGET_ARCH-}
source "${PROJECT_DIR}/target.env"
ARTIFACT_DIR=${ARTIFACT_DIR:-/artifacts}
mkdir -p "${ARTIFACT_DIR}"
export ARTIFACT_DIR

stage() {
  python3 "${PROJECT_DIR}/scripts/receipt.py" event "$1" "$2" "${3:-}"
}
reject() { stage target rejected "$1"; echo "ERROR: $1" >&2; exit 2; }
require_container() {
  [[ -f /run/.containerenv || -f /.dockerenv ]] || reject 'build/test work requires the isolated project container'
}
[[ -z "${REQUESTED_NVR}" || "${REQUESTED_NVR}" == "${DOVECOT_NVR}" ]] || reject 'NVR override differs from reviewed target'
[[ -z "${REQUESTED_ARCH}" || "${REQUESTED_ARCH}" == "${TARGET_ARCH}" ]] || reject 'architecture override differs from reviewed target'
[[ "$(uname -m)" == "${TARGET_ARCH}" ]] || reject 'build architecture differs from reviewed target'
[[ "${DOVECOT_NVR}" =~ ^dovecot-2\.3\.21-[1-9][0-9]*\.el10(_[0-9]+(\.[0-9]+)?)?$ ]] || reject 'unsupported runtime target'
[[ "${DOVECOT_EPOCH}" == 1 && "${BUILD_JOBS}" == 8 ]] || reject 'unsupported epoch or resource policy'
DOVE_VERSION=${DOVECOT_NVR#dovecot-}; DOVE_VERSION=${DOVE_VERSION%%-*}
DOVE_RELEASE=${DOVECOT_NVR#dovecot-${DOVE_VERSION}-}
DOVE_EVR=${DOVECOT_EPOCH}:${DOVE_VERSION}-${DOVE_RELEASE}
export DOVECOT_NVR DOVECOT_EPOCH TARGET_ARCH BUILD_JOBS DOVE_VERSION DOVE_RELEASE DOVE_EVR
CURRENT_STAGE=target
trap 'rc=$?; stage "${CURRENT_STAGE}" fail "exit=${rc} line=${LINENO}"; exit "${rc}"' ERR
stage target ok "${DOVECOT_NVR}.${TARGET_ARCH}"
