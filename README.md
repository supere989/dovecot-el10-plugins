# dovecot-el10-lua-plugins

This repository provides a Docker-based AlmaLinux 10 (EL10) build environment to compile Dovecot Lua-related plugin modules needed by Chatmail's Dovecot push-notification Lua handler.

## Why

On EL10, the distro Dovecot build may not ship the Lua plugin modules required by Chatmail:

- `mail_lua`
- `push_notification_lua`

Chatmail config enables these plugins for LMTP, so missing modules can break LMTP delivery.

## What this repo does

- Builds Dovecot source (default: `release-2.3.21`)
- Compiles the plugin `.so` files
- Writes the plugin artifacts to `/artifacts/plugins` inside the container

## Build

From this repo directory:

```bash
docker build -t dovecot-el10-lua-plugins .
mkdir -p artifacts
docker run --rm -v "$PWD/artifacts:/artifacts" dovecot-el10-lua-plugins
```

Artifacts will appear under:

- `./artifacts/plugins/`

## Deployment note

These `.so` plugin modules are **ABI-sensitive**.

- They must match the **exact Dovecot version/ABI** on the target server.
- If you update `dovecot` on the server, you typically must rebuild the plugins.

## Next steps

- Build a full Dovecot SRPM rebuild for EL10 with Lua enabled.
