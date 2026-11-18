Name:           dovecot-el10-lua-plugins
Version:        %{dovecot_version}
Release:        %{dovecot_release}.chatmail1
Summary:        Exact-ABI Lua modules for AlmaLinux Chatmail LMTP
License:        MIT AND LGPL-2.1-only
URL:            https://github.com/supere989/dovecot-el10-plugins
Requires:       dovecot(x86-64) = %{dovecot_epoch}:%{dovecot_version}-%{dovecot_release}
Requires:       lua-libs
BuildArch:      x86_64

%description
Lua-aware mail and push-notification modules for the exact reviewed AlmaLinux
Dovecot build. Private LMTP modules never replace Alma-owned plugin files.
Activation is a separate configuration change; this is not a drop-in upgrade
for historical overwrite-based packages or the legacy production timer.

%prep
%build
%install
install -d %{buildroot}/usr/lib64/dovecot/chatmail-lua
for name in lib01_mail_lua_plugin.so lib20_push_notification_plugin.so lib22_push_notification_lua_plugin.so; do
  install -m 0755 %{_sourcedir}/plugins/${name} %{buildroot}/usr/lib64/dovecot/chatmail-lua/${name}
done
for name in libauthdb_lua.so libdovecot-lua.so.0.0.0 libdovecot-storage-lua.so.0.0.0; do
  install -m 0755 %{_sourcedir}/plugins/${name} %{buildroot}/usr/lib64/dovecot/${name}
done
ln -s libdovecot-lua.so.0.0.0 %{buildroot}/usr/lib64/dovecot/libdovecot-lua.so.0
ln -s libdovecot-storage-lua.so.0.0.0 %{buildroot}/usr/lib64/dovecot/libdovecot-storage-lua.so.0
for name in lib10_quota_plugin.so lib15_notify_plugin.so lib20_zlib_plugin.so; do
  ln -s ../${name} %{buildroot}/usr/lib64/dovecot/chatmail-lua/${name}
done
install -Dm 0644 %{_sourcedir}/99-chatmail-lua.conf %{buildroot}%{_docdir}/%{name}/99-chatmail-lua.conf.example

%files
/usr/lib64/dovecot/chatmail-lua
/usr/lib64/dovecot/libauthdb_lua.so
/usr/lib64/dovecot/libdovecot-lua.so.0*
/usr/lib64/dovecot/libdovecot-storage-lua.so.0*
%{_docdir}/%{name}

%changelog
* Sun Nov 15 2026 Raymond Johnson <supere989@gmail.com> - current-Alma-candidate
- Exact core EVR; private LMTP module selection; no overwrite/restore scriptlets.
