#!/usr/bin/env bash
set -euo pipefail

DOVECOT_NVR="${DOVECOT_NVR:-dovecot-2.3.21-16.el10}"
ARTIFACT_DIR="${ARTIFACT_DIR:-/artifacts}"
TOPDIR="${TOPDIR:-/work/rpmbuild}"
SRPM_DIR="${SRPM_DIR:-/work/srpms}"

echo "Using Dovecot NVR: ${DOVECOT_NVR}"

echo "Preparing rpmbuild dirs"
rm -rf "${TOPDIR}" "${SRPM_DIR}"
mkdir -p "${TOPDIR}" "${SRPM_DIR}" "${ARTIFACT_DIR}"

dnf -y download --source --destdir "${SRPM_DIR}" "${DOVECOT_NVR}"
SRPM_PATH="$(ls -1 "${SRPM_DIR}"/*.src.rpm | head -n 1)"

rpm -i --define "_topdir ${TOPDIR}" "${SRPM_PATH}"
SPEC="$(ls -1 "${TOPDIR}"/SPECS/*.spec | head -n 1)"

echo "Patching spec to enable Lua"
if ! grep -qE '^BuildRequires:.*lua-devel' "${SPEC}"; then
  sed -i '0,/^BuildRequires:/s//&\nBuildRequires: lua\nBuildRequires: lua-devel\nBuildRequires: lua-libs/' "${SPEC}"
fi

# Normalize and force Lua configure option.
sed -r -i 's/--with-lua=no/--with-lua=plugin/g; s/--without-lua/--with-lua=plugin/g; s/--with-lua([^=[:alnum:]_-]|$)/--with-lua=plugin\1/g' "${SPEC}"
if ! grep -q -- '--with-lua' "${SPEC}"; then
  sed -i 's/%configure/%configure --with-lua=plugin/' "${SPEC}"
fi

# If SRPM gates lua behind a Fedora-only conditional, unwrap it.
SPEC_PATH="${SPEC}" python3 - <<'PY'
import os
from pathlib import Path

p = Path(os.environ["SPEC_PATH"])
s = p.read_text(errors="ignore")

lines = s.splitlines(keepends=True)
out = []
i = 0
while i < len(lines):
    line = lines[i]
    if line.lstrip().startswith('%if') and '%{?rhel}0' in line and '== 0' in line:
        block = [line]
        i += 1
        while i < len(lines):
            block.append(lines[i])
            if lines[i].lstrip().startswith('%endif'):
                i += 1
                break
            i += 1

        body_lines = block[1:-1] if len(block) >= 3 else []
        lua_lines = [l for l in body_lines if 'lua' in l.lower()]
        other_lines = [l for l in body_lines if 'lua' not in l.lower()]

        # If the block contains lua-related lines, move ONLY those out of the
        # conditional. Keep all other lines under the original condition so we
        # don't accidentally enable extra BuildRequires (e.g. libsodium-devel).
        if lua_lines:
            out.extend(lua_lines)
            if other_lines:
                out.append(block[0])
                out.extend(other_lines)
                out.append(block[-1])
        else:
            out.extend(block)
        continue
    out.append(line)
    i += 1

p.write_text(''.join(out))
PY

mkdir -p /artifacts
cp -a "${SPEC}" /artifacts/dovecot.srpm.patched.spec

dnf -y builddep "${SPEC}"

# Patch dlua compatibility for newer Lua (5.2+ / 5.3+) if needed.
SRC_TARBALL="$(ls -1 "${TOPDIR}"/SOURCES/dovecot-*.tar.* | head -n 1)"
if [[ -n "${SRC_TARBALL}" && -f "${SRC_TARBALL}" ]]; then
  TMP_SRC_DIR="$(mktemp -d)"
  tar -xf "${SRC_TARBALL}" -C "${TMP_SRC_DIR}"
  SRC_ROOT="$(find "${TMP_SRC_DIR}" -maxdepth 1 -type d -name 'dovecot-*' | head -n 1)"
  if [[ -n "${SRC_ROOT}" && -d "${SRC_ROOT}" ]]; then
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
  fi
  rm -rf "${TMP_SRC_DIR}"
fi

echo "Building full Dovecot RPM set"
rpmbuild \
  --define "_topdir ${TOPDIR}" \
  --nocheck \
  -bb "${SPEC}"

mkdir -p "${ARTIFACT_DIR}/dovecot-rpms" "${ARTIFACT_DIR}/dovecot-srpms"

if compgen -G "${TOPDIR}/RPMS/*/*.rpm" >/dev/null; then
  cp -a --no-preserve=ownership "${TOPDIR}/RPMS"/*/*.rpm "${ARTIFACT_DIR}/dovecot-rpms/"
fi
if compgen -G "${TOPDIR}/SRPMS/*.src.rpm" >/dev/null; then
  cp -a --no-preserve=ownership "${TOPDIR}/SRPMS"/*.src.rpm "${ARTIFACT_DIR}/dovecot-srpms/"
fi

echo
echo "Dovecot RPMs written to: ${ARTIFACT_DIR}/dovecot-rpms"
ls -la "${ARTIFACT_DIR}/dovecot-rpms" || true
