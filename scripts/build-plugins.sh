#!/usr/bin/env bash
set -euo pipefail

DOVECOT_NVR="${DOVECOT_NVR:-dovecot-2.3.21-16.el10}"
ARTIFACT_DIR="${ARTIFACT_DIR:-/artifacts/plugins}"
TOPDIR="${TOPDIR:-/work/rpmbuild}"
SRPM_DIR="${SRPM_DIR:-/work/srpms}"
FULL_BUILD="${FULL_BUILD:-1}"

echo "Using Dovecot NVR: ${DOVECOT_NVR}"

echo "Preparing rpmbuild dirs"
rm -rf "${TOPDIR}" "${SRPM_DIR}"
mkdir -p "${TOPDIR}" "${SRPM_DIR}" "${ARTIFACT_DIR}"

dnf -y download --source --destdir "${SRPM_DIR}" "${DOVECOT_NVR}"
SRPM_PATH="$(ls -1 "${SRPM_DIR}"/*.src.rpm | head -n 1)"

rpm -i --define "_topdir ${TOPDIR}" "${SRPM_PATH}"
SPEC="$(ls -1 "${TOPDIR}"/SPECS/*.spec | head -n 1)"

if ! grep -qE '^BuildRequires:.*lua-devel' "${SPEC}"; then
  sed -i '0,/^BuildRequires:/s//&\nBuildRequires: lua\nBuildRequires: lua-devel\nBuildRequires: lua-libs/' "${SPEC}"
fi

sed -r -i 's/--with-lua=no/--with-lua=plugin/g; s/--without-lua/--with-lua=plugin/g; s/--with-lua([^=[:alnum:]_-]|$)/--with-lua=plugin\1/g' "${SPEC}"
if ! grep -q -- '--with-lua' "${SPEC}"; then
  sed -i 's/%configure/%configure --with-lua=plugin/' "${SPEC}"
fi

if ! grep -q -- '--with-lua' "${SPEC}"; then
  sed -i '/^\s*%configure\b/ { /--with-lua/! s/%configure/%configure --with-lua=plugin/ }' "${SPEC}"
  sed -r -i '/^[[:space:]]*\.\/configure([[:space:]]|\\)/ { /--with-lua/! s|\.\/configure|./configure --with-lua=plugin| }' "${SPEC}"
fi

# Some specs use multiline configure invocations without a trailing space. Ensure
# the configure line itself is patched to include --with-lua.
sed -r -i '/^[[:space:]]*\.\/configure/ { /--with-lua/! s|(^[[:space:]]*\.\/configure)(.*)$|\1 --with-lua=plugin\2| }' "${SPEC}"

SPEC_PATH="${SPEC}" python3 - <<'PY'
import os
import re
from pathlib import Path

p = Path(os.environ["SPEC_PATH"])
s = p.read_text(errors="ignore")

# EL/RHEL SRPMs sometimes gate Lua behind a Fedora-only conditional.
# Unwrap the conditional so --with-lua=plugin is actually passed on EL10.
s2 = re.sub(
    r"%if\s+%\{\?rhel\}0\s*==\s*0\s*\n(\s*--with-lua=plugin\s*\\\\\s*\n)%endif\s*\n",
    r"\1",
    s,
    flags=re.M,
)

p.write_text(s2)
PY

mkdir -p /artifacts
cp -a "${SPEC}" /artifacts/dovecot.srpm.patched.spec

dnf -y builddep "${SPEC}"

if [[ "${FULL_BUILD}" == "1" ]]; then
  SRC_TARBALL="$(ls -1 "${TOPDIR}"/SOURCES/dovecot-*.tar.* | head -n 1)"
  if [[ -z "${SRC_TARBALL}" || ! -f "${SRC_TARBALL}" ]]; then
    echo "Unable to locate Dovecot source tarball under ${TOPDIR}/SOURCES" >&2
    ls -la "${TOPDIR}/SOURCES" || true
    exit 1
  fi

  TMP_SRC_DIR="$(mktemp -d)"
  tar -xf "${SRC_TARBALL}" -C "${TMP_SRC_DIR}"
  SRC_ROOT="$(find "${TMP_SRC_DIR}" -maxdepth 1 -type d -name 'dovecot-*' | head -n 1)"
  if [[ -z "${SRC_ROOT}" || ! -d "${SRC_ROOT}" ]]; then
    echo "Failed to find extracted dovecot-* directory in ${TMP_SRC_DIR}" >&2
    find "${TMP_SRC_DIR}" -maxdepth 2 -type d | head -n 50 || true
    exit 1
  fi

  SRC_ROOT_PATH="${SRC_ROOT}" python3 - <<'PY'
import os
from pathlib import Path

root = Path(os.environ['SRC_ROOT_PATH'])
p = root / 'src' / 'lib-lua' / 'dlua-compat.c'
if p.exists():
    s = p.read_text()
    needle = '#include "dlua-script-private.h"\n'
    if needle in s and 'HAVE_LUA_ISINTEGER' not in s:
        insert = needle + "\n#if LUA_VERSION_NUM >= 503\n#define HAVE_LUA_ISINTEGER 1\n#endif\n#if LUA_VERSION_NUM >= 502\n#define HAVE_LUA_TOINTEGERX 1\n#endif\n"
        p.write_text(s.replace(needle, insert, 1))
PY

  rm -f "${SRC_TARBALL}"
  tar -C "${TMP_SRC_DIR}" -caf "${SRC_TARBALL}" "$(basename "${SRC_ROOT}")"
  rm -rf "${TMP_SRC_DIR}"

  rpmbuild \
    --define "_topdir ${TOPDIR}" \
    --nocheck \
    --noclean \
    --with lua \
    -bb "${SPEC}"

  BUILD_DIR="$(find "${TOPDIR}/BUILD" -maxdepth 1 -type d -name 'dovecot-*' | head -n 1)"
  if [[ -n "${BUILD_DIR}" && -d "${BUILD_DIR}" ]]; then
    # The SRPM configure invocation may still omit --with-lua. If so, re-run the
    # exact configure command from config.status with --with-lua appended, then
    # build the Lua helper library + mail-lua plugin artifacts.
    need_lua_reconf=0
    if [[ ! -f "${BUILD_DIR}/src/lib-lua/Makefile" ]]; then
      need_lua_reconf=1
    fi
    if [[ -f "${BUILD_DIR}/config.log" ]] && grep -q "linking in Lua\.\.\. no" "${BUILD_DIR}/config.log"; then
      need_lua_reconf=1
    fi

    if [[ -f "${BUILD_DIR}/config.status" ]]; then
      cfg_args="$(BUILD_DIR="${BUILD_DIR}" python3 - <<'PY'
import os
import re
from pathlib import Path

build_dir = Path(os.environ['BUILD_DIR'])
p = build_dir / 'config.status'
s = p.read_text(errors='ignore')
m = re.search(r"ac_cs_config='(.*?)'", s, re.S)
if not m:
    print("")
else:
    print(m.group(1).strip())
PY
)"
      echo "config.status cfg_args length: ${#cfg_args}"
      if [[ "${need_lua_reconf}" == "1" && -n "${cfg_args}" && "${cfg_args}" != *"--with-lua"* ]]; then
        (cd "${BUILD_DIR}" && eval "./configure ${cfg_args} --with-lua")
        need_lua_reconf=0
      fi
    fi

    if [[ "${need_lua_reconf}" == "1" ]]; then
      (cd "${BUILD_DIR}" && ./configure --with-lua --prefix=/usr --sysconfdir=/etc --libdir=/usr/lib64 --with-rundir=/run/dovecot --with-systemd --disable-static --disable-rpath)
    fi

    if [[ -f "${BUILD_DIR}/config.log" ]]; then
      cp -a "${BUILD_DIR}/config.log" /artifacts/dovecot.config.log || true
    fi

    if [[ ! -f "${BUILD_DIR}/src/lib-lua/Makefile" ]]; then
      echo "Lua Makefile still missing after reconfigure: ${BUILD_DIR}/src/lib-lua/Makefile" >&2
      exit 1
    fi

    if [[ -f "${BUILD_DIR}/config.log" ]] && grep -q "linking in Lua\.\.\. no" "${BUILD_DIR}/config.log"; then
      echo "Lua is still disabled after reconfigure (see /artifacts/dovecot.config.log)" >&2
      exit 1
    fi

    # Build Lua components from the top-level so cross-directory dependencies can
    # be built (e.g., src/lib-lua depends on src/lib-dict/libdict_lua.la).
    lua_targets=(
      src/lib-lua/libdovecot-lua.la
      src/lib-storage/libdovecot-storage-lua.la
      src/plugins/mail-lua/lib01_mail_lua_plugin.la
    )
    for t in "${lua_targets[@]}"; do
      if make -C "${BUILD_DIR}" -n "${t}" >/dev/null 2>&1; then
        make -C "${BUILD_DIR}" "${t}"
      else
        echo "Skipping make target (no rule): ${t}"
      fi
    done
  fi

  BUILDROOT_DIR="$(find "${TOPDIR}/BUILDROOT" -maxdepth 1 -type d -name 'dovecot-*' | head -n 1)"
  if [[ -z "${BUILDROOT_DIR}" || ! -d "${BUILDROOT_DIR}" ]]; then
    echo "Unable to locate BUILDROOT under ${TOPDIR}/BUILDROOT" >&2
    ls -la "${TOPDIR}/BUILDROOT" || true
    exit 1
  fi

  SRC_LIBDIR="${BUILDROOT_DIR}/usr/lib64/dovecot"
  if [[ ! -d "${SRC_LIBDIR}" ]]; then
    echo "Expected directory not found: ${SRC_LIBDIR}" >&2
    find "${BUILDROOT_DIR}" -maxdepth 4 -type d -name dovecot | head -n 30 || true
    exit 1
  fi

  BUILD_DIR="$(find "${TOPDIR}/BUILD" -maxdepth 1 -type d -name 'dovecot-*' | head -n 1)"

  tmp_list_file="$(mktemp)"
  find "${SRC_LIBDIR}" -maxdepth 1 -type f \( -name '*mail*lua*plugin.so*' -o -name '*lua*.so*' -o -name '*push_notification*plugin.so*' \) ! -name '*.soT' -print >>"${tmp_list_file}" || true
  if [[ -n "${BUILD_DIR}" && -d "${BUILD_DIR}" ]]; then
    find "${BUILD_DIR}" -type f \( -name '*mail*lua*plugin.so*' -o -name 'libdovecot-lua.so*' -o -name '*lua*.so*' -o -name '*push_notification*plugin.so*' \) ! -name '*.soT' -print >>"${tmp_list_file}" || true
  fi

  mapfile -t copy_list < <(sort -u "${tmp_list_file}")
  rm -f "${tmp_list_file}"

  if (( ${#copy_list[@]} == 0 )); then
    echo "No Lua-related artifacts found in BUILDROOT/BUILD trees" >&2
    ls -la "${SRC_LIBDIR}" | head -n 200 || true
    if [[ -n "${BUILD_DIR}" ]]; then
      find "${BUILD_DIR}" -maxdepth 4 -type d -name '.libs' | head -n 40 || true
    fi
    exit 1
  fi

  declare -A copied=()
  for src in "${copy_list[@]}"; do
    base="$(basename "${src}")"
    if [[ -n "${copied["${base}"]+x}" ]]; then
      continue
    fi
    copied["${base}"]=1
    cp -a --no-preserve=ownership "${src}" "${ARTIFACT_DIR}/"
  done

  echo
  echo "Artifacts written to: ${ARTIFACT_DIR}"
  ls -la "${ARTIFACT_DIR}" || true
  exit 0
fi

echo "FULL_BUILD=0 is not supported by this staged script" >&2
exit 2
