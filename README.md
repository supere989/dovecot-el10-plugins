# dovecot-el10-plugins

Builds and publishes EL10-compatible Dovecot Lua + push-notification plugin modules as an installable RPM.

This repo is intended for deployments that enable Lua-related plugins but don’t get the required modules from the stock EL10 Dovecot packages.

## What you get

- `dovecot-el10-lua-plugins-*.rpm`
- Dovecot plugin `.so` modules (also attached to Releases for inspection)

## Releases

This repo publishes build outputs via **GitHub Releases**.

Releases are created automatically when pushing a `v*` tag (e.g. `v1.0.0`).

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
- The plugin modules are **ABI-sensitive** and must match the **exact Dovecot version/ABI** installed on the target server.
- If you update `dovecot` on the server, rebuild and reinstall.
