#!/usr/bin/env bash
set -euo pipefail

# Builds an RPM that installs only the missing Dovecot Lua plugin .so files.
# This script is intended to be run INSIDE the Docker build container after
# build-plugins.sh has produced /artifacts/plugins/*.so

RPMTOP="${RPMTOP:-/work/rpm}"
ARTIFACT_PLUGINS_DIR="${ARTIFACT_PLUGINS_DIR:-/artifacts/plugins}"
SPEC="${SPEC:-${RPMTOP}/SPECS/dovecot-el10-lua-plugins.spec}"

mkdir -p "${RPMTOP}/SOURCES/plugins"

shopt -s nullglob
plugins=("${ARTIFACT_PLUGINS_DIR}"/*.so*)
if (( ${#plugins[@]} == 0 )); then
  echo "No plugin .so artifacts found in ${ARTIFACT_PLUGINS_DIR}" >&2
  exit 1
fi
cp -a --no-preserve=ownership "${plugins[@]}" "${RPMTOP}/SOURCES/plugins/"

# Ensure rpmbuild exists
if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "rpmbuild not found; install rpm-build" >&2
  exit 1
fi

# rpmbuild will fail on 'invalid rpath' checks if build paths leak into RPATH.
# We allow invalid RPATHs here (0x0002) because these plugin .so files are
# compiled from a SRPM BUILD tree and may carry temporary build paths.
export QA_RPATHS=$(( 0x0002 ))

rpmbuild \
  --define "_topdir ${RPMTOP}" \
  -bb "${SPEC}"

# Copy built RPM(s) out to artifacts
mkdir -p /artifacts/rpms
cp -a --no-preserve=ownership "${RPMTOP}/RPMS"/*/*.rpm /artifacts/rpms/

echo "Built RPMs:" 
ls -la /artifacts/rpms || true
