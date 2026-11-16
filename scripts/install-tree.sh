#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
[[ $# == 2 ]] || reject 'install-tree requires prepared build and fresh staging paths'
# Alma's hardened GCC spec consults RPM_ARCH again during libtool's install
# relink, outside rpmbuild's environment. Keep its exact target architecture.
RPM_PACKAGE_NAME=dovecot RPM_PACKAGE_VERSION="${DOVE_VERSION}" \
  RPM_PACKAGE_RELEASE="${DOVE_RELEASE}" RPM_ARCH="${TARGET_ARCH}" \
  make -C "$1" install DESTDIR="$2" -j"${BUILD_JOBS}"
