Name:           dovecot-el10-lua-plugins
Version:        %{dovecot_version}
Release:        %{dovecot_release}%{?dist}
Summary:        Dovecot Lua plugin modules for EL10 (mail_lua, push_notification_lua)
License:        MIT
URL:            https://github.com/supere989/dovecot-el10-plugins

# No Source tarball: we build inside Docker and stage .so files into BUILDROOT.

Requires:       dovecot >= 1:%{dovecot_version}
Requires:       lua-libs

BuildArch:      x86_64

%description
Provides Dovecot Lua plugin modules (mail_lua and push_notification_lua) built for
EL10 to support Chatmail's Dovecot push-notification Lua handler.

This package intentionally does NOT replace the dovecot package.

%prep

%build

%install
mkdir -p %{buildroot}/usr/lib64/dovecot
mkdir -p %{buildroot}/usr/lib64/dovecot/lua-plugins

# The build system stages .so files here before rpmbuild runs (see build-rpm.sh)
if ls %{_sourcedir}/plugins/*lua*.so* >/dev/null 2>&1; then
  cp -a %{_sourcedir}/plugins/*lua*.so* %{buildroot}/usr/lib64/dovecot/
fi
cp -a %{_sourcedir}/plugins/*push_notification*plugin.so %{buildroot}/usr/lib64/dovecot/lua-plugins/

# Create versioned symlinks for the shared libraries
for lib in libdovecot-lua libdovecot-storage-lua; do
  sofile=$(ls %{buildroot}/usr/lib64/dovecot/${lib}.so.*.*.* 2>/dev/null | head -1)
  if [[ -n "${sofile}" ]]; then
    soname="${lib}.so.0"
    ln -sf "$(basename "${sofile}")" "%{buildroot}/usr/lib64/dovecot/${soname}"
  fi
done

FILELIST=dovecot-el10-lua-plugins.files
: > ${FILELIST}
find %{buildroot}/usr/lib64/dovecot -maxdepth 1 \( -type f -o -type l \) \
  -name '*lua*' \
  -printf '/usr/lib64/dovecot/%f\n' >> ${FILELIST} || true
find %{buildroot}/usr/lib64/dovecot/lua-plugins -maxdepth 1 -type f \
  -name '*push_notification*plugin.so' \
  -printf '/usr/lib64/dovecot/lua-plugins/%f\n' >> ${FILELIST} || true

%post
set -e

# Ensure versioned symlinks exist (in case of reinstall over a partial state)
for lib in libdovecot-lua libdovecot-storage-lua; do
  sofile=$(ls /usr/lib64/dovecot/${lib}.so.*.*.* 2>/dev/null | head -1)
  if [[ -n "${sofile}" && ! -L /usr/lib64/dovecot/${lib}.so.0 ]]; then
    ln -sf "$(basename "${sofile}")" "/usr/lib64/dovecot/${lib}.so.0"
  fi
done

# Copy our Lua-aware push_notification plugin over the stock one
if [ -f /usr/lib64/dovecot/lib20_push_notification_plugin.so ]; then
  if [ ! -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro ]; then
    cp -a /usr/lib64/dovecot/lib20_push_notification_plugin.so \
          /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro
  fi
fi
if [ -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so ]; then
  cp -a /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so \
        /usr/lib64/dovecot/lib20_push_notification_plugin.so
fi

%preun
set -e

if [ "$1" = "0" ]; then
  # Restore the original distro push_notification plugin on full uninstall
  if [ -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro ]; then
    cp -a /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro \
          /usr/lib64/dovecot/lib20_push_notification_plugin.so
  fi
  # Remove symlinks
  rm -f /usr/lib64/dovecot/libdovecot-lua.so.0
  rm -f /usr/lib64/dovecot/libdovecot-storage-lua.so.0
fi

%files -f dovecot-el10-lua-plugins.files

%changelog
* Tue May 12 2026 Raymond Johnson <supere989@gmail.com> - dynamic
- Dynamic versioning: Version/Release now set from DOVECOT_NVR at build time.
- Add versioned symlinks (libdovecot-lua.so.0, libdovecot-storage-lua.so.0) via %%post.
- Relax Requires to dovecot >= version (no dist-release pinning).

* Tue Dec 16 2025 Raymond Johnson <supere989@gmail.com> - 2.3.21-1.el10
- Initial EL10 build providing Dovecot Lua plugin modules for Chatmail.
