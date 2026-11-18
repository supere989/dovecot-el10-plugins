#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "$0")/.." && pwd)
ARTIFACT_DIR=${ARTIFACT_DIR:-/artifacts/runtime24}
export ARTIFACT_DIR
[[ ${EUID} == 0 && ${CHATMAIL_ISOLATED_LAB:-0} == 1 && ( -f /run/.containerenv || -f /.dockerenv ) ]]
[[ -d /relay/cmdeploy/src/cmdeploy && -f "${ARTIFACT_DIR}/manifest.json" ]]
stage() { python3 "${PROJECT_DIR}/scripts/receipt.py" event "$1" "$2" "${3:-}"; }
CURRENT_STAGE=runtime24-rpm-install
trap 'rc=$?; stage "${CURRENT_STAGE}" fail "exit=${rc} line=${LINENO}"; exit "${rc}"' ERR
rpm_path=$(python3 "${PROJECT_DIR}/scripts/verify-runtime-payload.py" select "${ARTIFACT_DIR}")
stock=$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)
rpm -i "${rpm_path}"
python3 "${PROJECT_DIR}/scripts/verify-runtime-payload.py" installed "${ARTIFACT_DIR}"
[[ "$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)" == "${stock}" ]]
stage runtime24-rpm-install ok 'exact RPM and installed private payload verified; stock module unchanged'
CURRENT_STAGE=runtime24-real-regression
python3 "${PROJECT_DIR}/tests/integration_runtime24.py"
stage runtime24-real-regression ok 'real offline IMAP/LMTP/Lua HTTP auth and metadata/notifier suites passed'
CURRENT_STAGE=runtime24-rpm-uninstall
rpm -e chatmail-dovecot-runtime
[[ "$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)" == "${stock}" ]]
stage runtime24-rpm-uninstall ok 'stock package bytes unchanged after private runtime uninstall'
