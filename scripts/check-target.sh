#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
CURRENT_STAGE=release-drift
available=$(dnf -q repoquery --latest-limit=1 --qf '%{name}-%{version}-%{release}.%{arch}' "dovecot.${TARGET_ARCH}")
[[ "${available}" == "${DOVECOT_NVR}.${TARGET_ARCH}" ]] || reject 'Alma latest differs from the reviewed target; review pin and rebuild before promotion'
stage release-drift ok 'reviewed target matches current Alma repository'
