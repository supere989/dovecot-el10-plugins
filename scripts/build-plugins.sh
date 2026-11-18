#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
CURRENT_STAGE=source
mkdir -p /work "${ARTIFACT_DIR}/inputs" "${ARTIFACT_DIR}/runtime"
BUILD_ROOT=$(mktemp -d /work/chatmail-build.XXXXXX)
TOPDIR=${BUILD_ROOT}/rpmbuild
mkdir -p "${TOPDIR}/SPECS" "${TOPDIR}/SOURCES"
dnf -y download --source --destdir "${ARTIFACT_DIR}/inputs" "${DOVECOT_NVR}"
shopt -s nullglob
srpms=("${ARTIFACT_DIR}/inputs/"*.src.rpm)
[[ ${#srpms[@]} == 1 ]] || reject 'expected exactly one source RPM'
SOURCE_RPM=${srpms[0]}
[[ "$(rpm -qp --qf '%{NAME}-%{VERSION}-%{RELEASE}' "${SOURCE_RPM}")" == "${DOVECOT_NVR}" ]] || reject 'downloaded source RPM identity mismatch'
rpmkeys --import /etc/pki/rpm-gpg/RPM-GPG-KEY-AlmaLinux-10
rpmkeys --checksig "${SOURCE_RPM}"
dnf -y download --destdir "${ARTIFACT_DIR}/runtime" \
  "dovecot-${DOVE_EVR}.${TARGET_ARCH}" "dovecot-pigeonhole-${DOVE_EVR}.${TARGET_ARCH}"
for name in dovecot dovecot-pigeonhole; do
  rpm_path=${ARTIFACT_DIR}/runtime/${name}-${DOVE_VERSION}-${DOVE_RELEASE}.${TARGET_ARCH}.rpm
  [[ "$(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' "${rpm_path}")" == "${DOVE_EVR}.${TARGET_ARCH}" ]] || reject 'runtime RPM identity mismatch'
  rpmkeys --checksig "${rpm_path}"
done
rpm -i --define "_topdir ${TOPDIR}" "${SOURCE_RPM}"
specs=("${TOPDIR}/SPECS/"*.spec)
[[ ${#specs[@]} == 1 ]] || reject 'expected exactly one distribution spec'
cp "${specs[0]}" "${ARTIFACT_DIR}/inputs/dovecot.original.spec"
python3 "${PROJECT_DIR}/scripts/prepare-spec.py" "${specs[0]}" "${TOPDIR}/SPECS/chatmail.spec"
SPEC=${TOPDIR}/SPECS/chatmail.spec
cp "${SPEC}" "${ARTIFACT_DIR}/inputs/dovecot.lua.spec"
dnf -y builddep "${SPEC}"
rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > "${ARTIFACT_DIR}/inputs/toolchain-rpms.txt"
rpmbuild --define "_topdir ${TOPDIR}" -bp "${SPEC}"
mapfile -t lua_sources < <(find "${TOPDIR}/BUILD" -mindepth 3 -maxdepth 6 -type f -path '*/src/lib-lua/dlua-compat.c')
[[ ${#lua_sources[@]} == 1 ]] || reject 'ambiguous prepared core source tree'
BUILD_DIR=${lua_sources[0]%/src/lib-lua/dlua-compat.c}
[[ -f "${BUILD_DIR}/configure" && -d "${BUILD_DIR}/dovecot-pigeonhole" ]] || reject 'unrecognized prepared core/Pigeonhole source layout'
# Keep the downloaded SRPM/archive unchanged. The compatibility change is an
# explicit, hashed patch applied after all distribution patches by %prep.
patch --forward -d "${BUILD_DIR}" -p1 < "${PROJECT_DIR}/patches/lua54-compat.patch"
stage source ok 'verified distribution inputs; security prep patches retained'
CURRENT_STAGE=compile
# --short-circuit resumes after %prep, preserving the explicit compatibility patch.
rpmbuild --define "_topdir ${TOPDIR}" --define "_smp_mflags -j${BUILD_JOBS}" \
  --short-circuit --nocheck -bc "${SPEC}"
cp "${BUILD_DIR}/config.log" "${ARTIFACT_DIR}/inputs/config.log"
grep -Eq '^#define HAVE_LUA 1|^#define HAVE_LUA_H 1' "${BUILD_DIR}/config.h"
STAGE_ROOT=${BUILD_ROOT}/installed
bash "${PROJECT_DIR}/scripts/install-tree.sh" "${BUILD_DIR}" "${STAGE_ROOT}"
python3 "${PROJECT_DIR}/scripts/select-artifacts.py" "${STAGE_ROOT}" "${ARTIFACT_DIR}/plugins"
stage compile ok 'single installed tree; Lua enabled; bounded build'
