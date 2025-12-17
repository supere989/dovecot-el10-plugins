#!/usr/bin/env bash
set -euo pipefail

if [[ "${BUILD_DOVECOT_RPMS:-0}" == "1" ]]; then
  /work/scripts/build-dovecot-rpms.sh
  exit 0
fi

# Build plugins
/work/scripts/build-plugins.sh

# Build RPM (optional)
if [[ "${BUILD_RPM:-1}" == "1" ]]; then
  /work/scripts/build-rpm.sh
fi
