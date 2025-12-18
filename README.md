# dovecot-el10-plugins

Build and publish AlmaLinux 10 / EL10-compatible Dovecot plugin artifacts (Lua + push notification support) as an installable RPM.

This exists because the stock EL10 Dovecot build may not ship the Lua-related modules required by deployments that enable Lua + push notification integrations.

## What this project produces

- A built RPM:
  - `dovecot-el10-lua-plugins-*.rpm`
- Plugin shared objects (for inspection/debugging):
  - `lib20_push_notification_plugin.so`
  - Lua-related plugin/module `.so` files (e.g. mail-lua / libdovecot-lua)
- Build provenance artifacts:
  - `dovecot.srpm.patched.spec`
  - `dovecot.config.log`

## Releases

This repo publishes build outputs via **GitHub Releases**.

- Push tags like `v1.0.0` to create a release.
- Release assets include the RPM and the extracted `.so` files.

## Install (from a Release)

Download the RPM from the GitHub Release page and install it on your EL10 host:

```bash
sudo dnf install -y ./dovecot-el10-lua-plugins-*.rpm
```

After installation, the plugin modules will be under Dovecot’s module directory (typically `/usr/lib64/dovecot/`).

## Build locally

From this repo directory:

```bash
docker build -t dovecot-el10-lua-plugins .
mkdir -p artifacts
docker run --rm -v "$PWD/artifacts:/artifacts" dovecot-el10-lua-plugins
```

Artifacts will appear under:

- `./artifacts/plugins/`
- `./artifacts/rpms/`

## Versioning and compatibility

- The repo uses semantic version tags (e.g. `v1.0.0`) to version the build pipeline and packaging.
- The produced `.so` modules are **ABI-sensitive** and must match the **exact Dovecot version/ABI** on the target server.
- If you update `dovecot` on the server, you should rebuild and reinstall the plugins.
