#!/usr/bin/env bash
set -euo pipefail

# Builds an RPM that installs only the missing Dovecot Lua plugin .so files.
# This script is intended to be run INSIDE the Docker build container after
# build-plugins.sh has produced /artifacts/plugins/*.so

RPMTOP="${RPMTOP:-/work/rpm}"
ARTIFACT_PLUGINS_DIR="${ARTIFACT_PLUGINS_DIR:-/artifacts/plugins}"
SPEC="${SPEC:-${RPMTOP}/SPECS/dovecot-el10-lua-plugins.spec}"

# Parse DOVECOT_NVR (e.g. "dovecot-2.3.21-16.el10") into version + release
DOVECOT_NVR="${DOVECOT_NVR:-dovecot-2.3.21-16.el10}"
NVR_STRIPPED="${DOVECOT_NVR#dovecot-}"
DOVE_VERSION=$(echo "${NVR_STRIPPED}" | cut -d'-' -f1)
DOVE_RELEASE=$(echo "${NVR_STRIPPED}" | cut -d'-' -f2-)

echo "Building RPM for Dovecot ${DOVE_VERSION}-${DOVE_RELEASE}"

mkdir -p "${RPMTOP}/SOURCES/plugins"

shopt -s nullglob
plugins=("${ARTIFACT_PLUGINS_DIR}"/*.so*)
if (( ${#plugins[@]} == 0 )); then
  echo "No plugin .so artifacts found in ${ARTIFACT_PLUGINS_DIR}" >&2
  exit 1
fi
cp -a --no-preserve=ownership "${plugins[@]}" "${RPMTOP}/SOURCES/plugins/"

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild not found; install rpm-build" >&2
  exit 1
fi

# Allow build-path RPATHs in plugin .so files compiled from a SRPM BUILD tree
export QA_RPATHS=$(( 0x0002 ))

rpmbuild \
  --define "_topdir ${RPMTOP}" \
  --define "dovecot_version ${DOVE_VERSION}" \
  --define "dovecot_release ${DOVE_RELEASE}" \
  -bb "${SPEC}"

mkdir -p /artifacts/rpms
cp -a --no-preserve=ownership "${RPMTOP}/RPMS"/*/*.rpm /artifacts/rpms/

echo "Built RPMs:"
ls -la /artifacts/rpms || true
