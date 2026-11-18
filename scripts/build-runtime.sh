#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR=$(cd -- "$(dirname -- "$0")/.." && pwd)
ARTIFACT_DIR=${ARTIFACT_DIR:-/artifacts/runtime24}
export ARTIFACT_DIR
mkdir -p "${ARTIFACT_DIR}"
stage() { python3 "${PROJECT_DIR}/scripts/receipt.py" event "$1" "$2" "${3:-}"; }
CURRENT_STAGE=runtime24-profile
trap 'rc=$?; stage "${CURRENT_STAGE}" fail "exit=${rc} line=${LINENO}"; exit "${rc}"' ERR
[[ -f /run/.containerenv || -f /.dockerenv ]] || { stage runtime24-profile rejected 'isolated project container required'; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { stage runtime24-profile rejected 'unqualified architecture'; exit 2; }
if [[ "${RUNTIME24_SOURCE_SNAPSHOT:-0}" != 1 ]]; then
  if [[ -e "${PROJECT_DIR}/candidate-context.json" ]]; then
    SOURCE_REVISION=$(python3 "${PROJECT_DIR}/scripts/upstream-candidate.py" validate "${PROJECT_DIR}")
  else
    SOURCE_REVISION=$(git -c "safe.directory=${PROJECT_DIR}" -C "${PROJECT_DIR}" rev-parse HEAD)
  fi
  snapshot=$(mktemp -d /work/runtime24-source.XXXXXX)
  for input in scripts rpm profiles patches tests examples docs target.env runtime-target.json Dockerfile Dockerfile.lab Dockerfile.runtime Dockerfile.runtime-lab README.md; do
    cp -a "${PROJECT_DIR}/${input}" "${snapshot}/${input}"
  done
  if [[ -e "${PROJECT_DIR}/candidate-context.json" ]]; then
    cp "${PROJECT_DIR}/candidate-context.json" "${PROJECT_DIR}/target.diff" "${snapshot}/"
  fi
  export SOURCE_REVISION RUNTIME24_SOURCE_SNAPSHOT=1
  exec bash "${snapshot}/scripts/build-runtime.sh"
fi
[[ ! -e "${ARTIFACT_DIR}/installed" && ! -e "${ARTIFACT_DIR}/rpms" ]] || { stage runtime24-profile rejected 'fresh runtime artifact directory required'; exit 2; }
mapfile -t runtime_fields < <(python3 "${PROJECT_DIR}/scripts/runtime_profile.py" "${PROJECT_DIR}")
[[ ${#runtime_fields[@]} == 4 ]] || { stage runtime24-profile rejected 'invalid profile'; exit 2; }
PROFILE=${runtime_fields[0]}
PREFIX=${runtime_fields[1]}
VERSION=${runtime_fields[2]}
PIGEONHOLE_VERSION=${runtime_fields[3]}
BUILD_ROOT=$(mktemp -d /work/runtime24-build.XXXXXX)
CURRENT_STAGE=runtime24-inputs
python3 "${PROJECT_DIR}/scripts/runtime-inputs.py" "${PROFILE}" "${ARTIFACT_DIR}/inputs" "${BUILD_ROOT}"
cp "${PROFILE}" "${ARTIFACT_DIR}/inputs/runtime-profile.json"
if [[ -e "${PROJECT_DIR}/candidate-context.json" ]]; then
  cp "${PROJECT_DIR}/candidate-context.json" "${PROJECT_DIR}/target.diff" "${ARTIFACT_DIR}/inputs/"
fi
stage runtime24-inputs ok 'official core/Pigeonhole archives and exact primary signer verified'
export CFLAGS='-O2 -g -fstack-protector-strong -D_FORTIFY_SOURCE=3'
export LDFLAGS='-Wl,-z,relro,-z,now'
CORE=${BUILD_ROOT}/dovecot-${VERSION}
PIGEONHOLE=${BUILD_ROOT}/dovecot-pigeonhole-${PIGEONHOLE_VERSION}
CURRENT_STAGE=runtime24-compile
cd "${CORE}"
./configure --prefix="${PREFIX}" --libdir="${PREFIX}/lib64" \
  --sysconfdir="${PREFIX}/etc" --localstatedir="${PREFIX}/var" \
  --with-rundir="${PREFIX}/run" --disable-static --with-lua=plugin \
  --with-ssl=openssl --with-zlib --with-zstd --with-systemd --with-pcre2 --without-docs
make -j8
cp config.log "${ARTIFACT_DIR}/inputs/core-config.log"
make install DESTDIR="${BUILD_ROOT}/installed" -j8
cd "${PIGEONHOLE}"
./configure --prefix="${PREFIX}" --libdir="${PREFIX}/lib64" \
  --sysconfdir="${PREFIX}/etc" --localstatedir="${PREFIX}/var" \
  --with-dovecot="${CORE}" --disable-static
make -j8
cp config.log "${ARTIFACT_DIR}/inputs/pigeonhole-config.log"
make install DESTDIR="${BUILD_ROOT}/installed" -j8
stage runtime24-compile ok 'coherent upstream core/Pigeonhole/Lua; no Alma modules'
CURRENT_STAGE=runtime24-native-tests
# The production payload was installed from unmodified signed source. These
# corrections affect only test mains/fixtures; retain their exact accounting.
python3 "${PROJECT_DIR}/scripts/runtime-test-patches.py" "${PROJECT_DIR}" "${CORE}" "${ARTIFACT_DIR}/inputs/test-only-patches.json"
# Native tests test privilege failures and must run as an unprivileged identity.
# Pigeonhole invokes the compiled absolute prefix. Expose only this staged
# payload inside the task container; no host path or service is activated.
[[ ${EUID} == 0 && ! -e "${PREFIX}" && ! -L "${PREFIX}" ]]
mkdir -p "$(dirname -- "${PREFIX}")"
ln -s "${BUILD_ROOT}/installed${PREFIX}" "${PREFIX}"
chown -R nobody:nobody "${CORE}" "${PIGEONHOLE}"
chmod 755 "${BUILD_ROOT}"
runuser -u nobody -- make -C "${CORE}" check -j8 2>&1 | tee "${ARTIFACT_DIR}/core-native-check.log"
runuser -u nobody -- make -C "${PIGEONHOLE}" check -j8 2>&1 | tee "${ARTIFACT_DIR}/pigeonhole-native-check.log"
stage runtime24-native-tests ok 'upstream core and Pigeonhole suites passed'
CURRENT_STAGE=runtime24-package
python3 "${PROJECT_DIR}/scripts/package-runtime.py" "${PROJECT_DIR}" "${BUILD_ROOT}/installed" "${ARTIFACT_DIR}"
stage runtime24-package ok 'private-prefix candidate only; no service activation'
