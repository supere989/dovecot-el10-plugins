#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
[[ "${CHATMAIL_ISOLATED_LAB:-0}" == 1 && -f /run/.containerenv || "${CHATMAIL_ISOLATED_LAB:-0}" == 1 && -f /.dockerenv ]] || reject 'runtime suite requires explicit isolated container'
CURRENT_STAGE=runtime-setup
[[ "${CHATMAIL_LAB_PREPARED:-0}" == 1 ]] || reject 'prepare the runtime image with Dockerfile.lab before the offline suite'
shopt -s nullglob
core=("${ARTIFACT_DIR}/runtime/dovecot-${DOVE_VERSION}-${DOVE_RELEASE}.${TARGET_ARCH}.rpm")
addon=("${ARTIFACT_DIR}/rpms/"*.rpm)
[[ ${#addon[@]} == 1 ]] || reject 'expected one addon candidate'
for name in dovecot dovecot-pigeonhole; do
  [[ "$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "${name}")" == "${DOVE_EVR}.${TARGET_ARCH}" ]] || reject 'prepared runtime identity mismatch'
done
STOCK_BEFORE=$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)
rpm -Uvh "${addon[0]}"
[[ "$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)" == "${STOCK_BEFORE}" ]] || reject 'addon altered stock push plugin'
id labmail >/dev/null 2>&1 || useradd --uid 5000 --no-create-home --home-dir /nonexistent labmail
CURRENT_STAGE=runtime
python3 "${PROJECT_DIR}/tests/integration_lmtp.py"
stage runtime ok 'real LMTP/Lua; synthetic Unix-socket metadata; no external push'
CURRENT_STAGE=uninstall
rpm -e dovecot-el10-lua-plugins
[[ "$(sha256sum /usr/lib64/dovecot/lib20_push_notification_plugin.so)" == "${STOCK_BEFORE}" ]] || reject 'addon uninstall altered stock plugin'
stage uninstall ok 'stock push library unchanged across install and uninstall'
