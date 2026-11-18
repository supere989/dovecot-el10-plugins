#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/common.sh"
require_container
if [[ "${CHATMAIL_SOURCE_SNAPSHOT:-0}" != 1 ]]; then
  # Bash can reread script bytes after a long child process. Freeze every build
  # input once, so concurrent review edits cannot alter the executing program.
  if [[ -f "${PROJECT_DIR}/candidate-context.json" ]]; then
    SOURCE_REVISION=$(python3 "${PROJECT_DIR}/scripts/read-candidate-context.py" "${PROJECT_DIR}" "${DOVECOT_NVR}")
  else
    SOURCE_REVISION=$(git -c "safe.directory=${PROJECT_DIR}" -C "${PROJECT_DIR}" rev-parse HEAD)
  fi
  [[ "${SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]] || reject 'source revision is not a full Git object ID'
  snapshot=$(mktemp -d /work/chatmail-source.XXXXXX)
  for input in scripts rpm patches tests examples docs target.env Dockerfile Dockerfile.lab README.md; do
    cp -a "${PROJECT_DIR}/${input}" "${snapshot}/${input}"
  done
  if [[ -f "${PROJECT_DIR}/candidate-context.json" ]]; then
    cp "${PROJECT_DIR}/candidate-context.json" "${snapshot}/candidate-context.json"
    cp "${PROJECT_DIR}/target.diff" "${snapshot}/target.diff"
  fi
  export SOURCE_REVISION CHATMAIL_SOURCE_SNAPSHOT=1
  exec bash "${snapshot}/scripts/entrypoint.sh"
fi
[[ "${BUILD_DOVECOT_RPMS:-0}" == 0 ]] || reject 'full replacement core RPM builds are not supported by this addon candidate'
[[ ! -e "${ARTIFACT_DIR}/plugins" && ! -e "${ARTIFACT_DIR}/rpms" ]] || reject 'use a fresh artifact directory; prior evidence is preserved'
bash "${PROJECT_DIR}/scripts/build-plugins.sh"
bash "${PROJECT_DIR}/scripts/build-rpm.sh"
CURRENT_STAGE=manifest
python3 "${PROJECT_DIR}/scripts/receipt.py" manifest "${PROJECT_DIR}" "${ARTIFACT_DIR}"
stage manifest ok 'candidate only; no deployment or publication'
