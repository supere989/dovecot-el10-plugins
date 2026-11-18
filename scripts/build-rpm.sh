#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
CURRENT_STAGE=package
RPMTOP=$(mktemp -d /work/chatmail-rpm.XXXXXX)
mkdir -p "${RPMTOP}/SOURCES/plugins" "${RPMTOP}/SPECS" "${ARTIFACT_DIR}/rpms"
for name in lib01_mail_lua_plugin.so lib20_push_notification_plugin.so lib22_push_notification_lua_plugin.so libauthdb_lua.so libdovecot-lua.so.0.0.0 libdovecot-storage-lua.so.0.0.0; do
  cp "${ARTIFACT_DIR}/plugins/${name}" "${RPMTOP}/SOURCES/plugins/${name}"
done
cp "${PROJECT_DIR}/rpm/SPECS/dovecot-el10-lua-plugins.spec" "${RPMTOP}/SPECS/"
cp "${PROJECT_DIR}/examples/99-chatmail-lua.conf" "${RPMTOP}/SOURCES/"
rpmbuild --define "_topdir ${RPMTOP}" --define "dovecot_version ${DOVE_VERSION}" \
  --define "dovecot_release ${DOVE_RELEASE}" --define "dovecot_epoch ${DOVECOT_EPOCH}" \
  -bb "${RPMTOP}/SPECS/dovecot-el10-lua-plugins.spec"
shopt -s nullglob
rpms=("${RPMTOP}/RPMS/${TARGET_ARCH}/"*.rpm)
[[ ${#rpms[@]} == 1 ]] || reject 'expected one addon RPM'
cp "${rpms[0]}" "${ARTIFACT_DIR}/rpms/"
stage package ok 'exact core dependency; private LMTP modules; no package scriptlets'
