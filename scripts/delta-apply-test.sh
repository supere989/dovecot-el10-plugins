#!/usr/bin/env bash
set -euo pipefail

RPM_PATH="${1:-}"
if [[ -z "${RPM_PATH}" ]]; then
  RPM_PATH=$(ls -1 /root/dovecot-el10-lua-plugins-*.rpm 2>/dev/null | sort | tail -n 1 || true)
fi
if [[ -z "${RPM_PATH}" || ! -f "${RPM_PATH}" ]]; then
  echo "RPM not found. Pass path as first argument or place it under /root/." >&2
  exit 2
fi

USER_ADDR="${USER_ADDR:-echo@chat.active-iq.com}"

echo "== upgrade rpm =="
dnf -y upgrade "${RPM_PATH}"

echo
echo "== installed version =="
rpm -q dovecot-el10-lua-plugins || true

echo
echo "== check duplicates =="
ls -la /usr/lib64/dovecot/*mail_lua* 2>/dev/null || true
if [[ -e /usr/lib64/dovecot/mail_lua_plugin.so ]]; then
  TS=$(date +%F-%H%M%S)
  mv -v /usr/lib64/dovecot/mail_lua_plugin.so "/usr/lib64/dovecot/mail_lua_plugin.so.disabled.${TS}"
fi

echo
echo "== NEEDED deps =="
readelf -d /usr/lib64/dovecot/lib01_mail_lua_plugin.so | grep -E 'NEEDED|RPATH|RUNPATH' || true
ls -la /usr/lib64/dovecot/libdovecot-lua.so* 2>/dev/null || true

echo
echo "== restart dovecot =="
systemctl restart dovecot
systemctl is-active dovecot

echo
echo "== doveconf checks =="
doveconf -n | sed -n '/^protocol lmtp {/,/^}/p'
doveconf -n | sed -n '/^plugin {/,/^}/p'
doveconf -n | sed -n '/^service push_notification {/,/^}/p'

echo
echo "== metadata before =="
doveadm mailbox metadata get -u "${USER_ADDR}" -s /private/messagenew INBOX 2>/dev/null || echo "(no /private/messagenew value)"

echo
echo "== send test mail =="
SUBJ="push-test $(date -u +%FT%TZ)"
printf "From: test@chat.active-iq.com\nTo: ${USER_ADDR}\nSubject: ${SUBJ}\n\nTest push notification.\n" | /usr/sbin/sendmail -f test@chat.active-iq.com "${USER_ADDR}"
echo "sent: ${SUBJ}"

sleep 3

echo
echo "== metadata after =="
doveadm mailbox metadata get -u "${USER_ADDR}" -s /private/messagenew INBOX 2>/dev/null || echo "(no /private/messagenew value)"

echo
echo "== socket check =="
ls -la /run/dovecot 2>/dev/null | grep -E 'push_notification' || true
ls -la /run/dovecot/push_notification 2>/dev/null || true

echo
echo "== recent dovecot lmtp/lua/push lines =="
journalctl -u dovecot --no-pager -n 200 | grep -E 'lmtp\(|mail_lua|dlua_|lua_tolstring|push_notification|push-notification|notify|Multiple files for module mail_lua_plugin|Couldn.t load required plugin' | tail -n 200 || true
