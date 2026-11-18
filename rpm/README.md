# Package contract

The candidate addon requires the exact architecture-qualified Alma core EVR in
`target.env`, while retaining generated ELF dependencies. Its own release suffix
is `.chatmail1`; source/core identity remains recorded independently.

`/usr/lib64/dovecot/chatmail-lua/` owns the custom mail-Lua and Lua-aware push
modules, plus symlinks to the matching stock quota, zlib and notify modules.
Lua helper libraries have explicit packaged filenames and SONAME symlinks.
There are no install/uninstall scriptlets and no `.distro` backup restoration.

The example configuration is documentation only. Enabling the private directory
is a separate reviewed LMTP config change. Installation alone does not repair
the historical overwritten stock library. The old addon must be migrated with
the exact core RPM and verified readback as described in `docs/upgrade.md`.

An exact RPM requirement is necessary but is not proof of ABI behavior. The
isolated runtime suite loads the real rebuilt modules against the signed core,
exercises delivery and checks stock hashes before/after addon install/removal.
Candidate signing and a proven recovery source are promotion prerequisites.
