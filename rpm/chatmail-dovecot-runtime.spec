Name:           chatmail-dovecot-runtime
Version:        %{runtime_version}
Release:        1.el10
Summary:        Coherent private Dovecot/Pigeonhole/Lua Chatmail runtime candidate
License:        MIT AND LGPL-2.1-only
URL:            https://github.com/supere989/dovecot-el10-plugins
BuildArch:      x86_64
%global _build_id_links none
%global debug_package %{nil}
Requires:       openssl-libs, lua-libs, zlib, libzstd, libxcrypt
# Internal module interfaces belong to this private runtime, not the host's
# stock Dovecot ABI. Retain external generated ELF requirements.
%global __provides_exclude_from ^/opt/chatmail-dovecot/%{version}/.*$
%global __requires_exclude ^lib(dovecot[^ ]*|sieve[^ ]*|[0-9]+_[A-Za-z0-9_]+_plugin)\.so.*$

%description
Upstream Dovecot and matching Pigeonhole/Lua support under an
independent /opt prefix. This package does not replace stock Dovecot, configure
a production instance, install a service unit or activate mail delivery.

%prep
%build
%install
mkdir -p %{buildroot}/opt/chatmail-dovecot
cp -a %{_sourcedir}/runtime/opt/chatmail-dovecot/%{version} %{buildroot}/opt/chatmail-dovecot/

%files
%defattr(-,root,root,-)
%dir /opt/chatmail-dovecot
/opt/chatmail-dovecot/%{version}
