Name:           dovecot-el10-lua-plugins
Version:        2.3.21
Release:        9.el10%{?dist}
Summary:        Dovecot Lua plugin modules for EL10 (mail_lua, push_notification_lua)
License:        MIT
URL:            https://github.com/supere989/dovecot-el10-lua-plugins

# No Source tarball: we build inside Docker and stage .so files into BUILDROOT.

# Strict pinning to the exact Dovecot EVR on delta:
Requires:       dovecot = 1:%{version}-16.el10
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

# The build system is expected to place the plugin .so files in the staging dir
# before rpmbuild runs.
#
# See scripts/build-rpm.sh
if ls %{_sourcedir}/plugins/*lua*.so* >/dev/null 2>&1; then
  cp -a %{_sourcedir}/plugins/*lua*.so* %{buildroot}/usr/lib64/dovecot/
fi
cp -a %{_sourcedir}/plugins/*push_notification*plugin.so %{buildroot}/usr/lib64/dovecot/lua-plugins/

FILELIST=dovecot-el10-lua-plugins.files
: > ${FILELIST}
if [ -d %{buildroot}/usr/lib64/dovecot ]; then
  find %{buildroot}/usr/lib64/dovecot -maxdepth 1 -type f -name '*lua*.so*' -printf '/usr/lib64/dovecot/%f\n' >> ${FILELIST} || true
fi
if [ -d %{buildroot}/usr/lib64/dovecot/lua-plugins ]; then
  find %{buildroot}/usr/lib64/dovecot/lua-plugins -maxdepth 1 -type f -name '*push_notification*plugin.so' -printf '/usr/lib64/dovecot/lua-plugins/%f\n' >> ${FILELIST} || true
fi

%post
set -e

if [ -f /usr/lib64/dovecot/lib20_push_notification_plugin.so ]; then
  if [ ! -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro ]; then
    cp -a /usr/lib64/dovecot/lib20_push_notification_plugin.so /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro
  fi
fi

if [ -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so ]; then
  cp -a /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so /usr/lib64/dovecot/lib20_push_notification_plugin.so
fi

%preun
set -e

if [ "$1" = "0" ]; then
  if [ -f /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro ]; then
    cp -a /usr/lib64/dovecot/lua-plugins/lib20_push_notification_plugin.so.distro /usr/lib64/dovecot/lib20_push_notification_plugin.so
  fi
fi

%files -f dovecot-el10-lua-plugins.files

%changelog
* Tue Dec 16 2025 Raymond Johnson <supere989@gmail.com> - 2.3.21-1.el10
- Initial EL10 build providing Dovecot Lua plugin modules for Chatmail.
