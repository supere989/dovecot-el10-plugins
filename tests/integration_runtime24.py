#!/usr/bin/env python3
"""Offline real IMAP/LMTP/Lua/relay service and storage-transition qualification."""

import base64
import concurrent.futures
import gzip
import hashlib
import imaplib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELAY = Path(os.environ.get("RELAY_SOURCE", "/relay"))
sys.path[:0] = [str(RELAY / "chatmaild/src"), str(RELAY / "cmdeploy/src")]
from chatmaild.config import read_config, write_initial_config
from chatmaild.doveauth import encrypt_password
from cmdeploy.runtime24 import Runtime24Paths, render

sys.path.insert(0, str(ROOT / "scripts"))
from runtime_profile import selected

_, PROFILE = selected(ROOT)
PREFIX = Path(PROFILE["prefix"])
DOMAIN = "synthetic.test"
imaplib.Commands.setdefault("SETMETADATA", ("AUTH", "SELECTED"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("bounded fixture condition did not complete")


def listening(listener_port):
    try:
        with socket.create_connection(("127.0.0.1", listener_port), timeout=0.1):
            return True
    except OSError:
        return False


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class PushHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        token = self.rfile.read(int(self.headers["Content-Length"]))
        with self.server.lock:
            self.server.attempts.append(token)
            status = (
                503
                if self.server.failing
                else (410 if token in self.server.invalid else 200)
            )
            if status == 200:
                self.server.completed.append(token)
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class FixtureImap(imaplib.IMAP4_SSL):
    """Give each independent auth case its own loopback penalty identity."""

    def __init__(self, *args, source_address, **kwargs):
        self.fixture_source = source_address
        super().__init__(*args, **kwargs)

    def _create_socket(self, timeout):
        connection = socket.create_connection(
            (self.host, self.port),
            timeout=timeout,
            source_address=(self.fixture_source, 0),
        )
        return self.ssl_context.wrap_socket(connection, server_hostname=self.host)


def message(identifier, references="", body=b"synthetic message"):
    headers = (
        f"From: sender@{DOMAIN}\r\nSubject: isolated runtime qualification\r\n"
        f"Message-ID: <{identifier}@{DOMAIN}>\r\nDate: Mon, 16 Nov 2026 00:00:00 +0000\r\n"
    )
    if references:
        headers += f"References: {references}\r\n"
    return headers.encode() + b"\r\n" + body + b"\r\n"


def lmtp(path, recipient, sender=None, payload=None):
    sender = sender or f"sender@{DOMAIN}"
    payload = payload or message("incoming")
    payload = payload.replace(b"\r\n.", b"\r\n..")
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(15)
        connection.connect(str(path))
        stream = connection.makefile("rwb", buffering=0)

        def reply():
            while True:
                result = stream.readline().decode(errors="replace")
                if not result:
                    raise AssertionError("LMTP disconnected")
                if len(result) < 4 or result[3] != "-":
                    return result

        assert reply().startswith("220")
        for command in (
            "LHLO synthetic.test",
            f"MAIL FROM:<{sender}>",
            f"RCPT TO:<{recipient}>",
        ):
            stream.write((command + "\r\n").encode())
            result = reply()
            if not result.startswith("250"):
                return result
        stream.write(b"DATA\r\n")
        assert reply().startswith("354")
        connection.sendall(payload + b".\r\n")
        result = reply()
        if result.startswith("5"):
            return result
        stream.write(b"QUIT\r\n")
        reply()
        return result


def mailbox_snapshot(client):
    assert client.select("INBOX")[0] == "OK"
    validity = client.response("UIDVALIDITY")[1][0].decode()
    result, rows = client.fetch("1:*", "(UID FLAGS BODY.PEEK[])")
    assert result == "OK"
    messages = []
    for row in rows:
        if isinstance(row, tuple):
            uid = int(re.search(rb"UID (\d+)", row[0]).group(1))
            # Recent belongs to the selecting session, not persisted Maildir
            # state. Compare every persistent flag across the daemon boundary.
            flags = sorted(
                flag
                for flag in re.search(rb"FLAGS \(([^)]*)\)", row[0])
                .group(1)
                .decode()
                .split()
                if flag != "\\Recent"
            )
            messages.append({"uid": uid, "flags": flags, "sha256": digest(row[1])})
    return {"uidvalidity": validity, "messages": messages}


class CompressedImap:
    """A bounded wire client retaining each command's raw DEFLATE output."""

    def __init__(self, listener_port, user, password, context=None):
        self.socket = socket.create_connection(("127.0.0.1", listener_port), timeout=5)
        if context is not None:
            self.socket = context.wrap_socket(self.socket, server_hostname="127.0.0.1")
        self.decoder, self.encoder, self.buffer, self.sequence = None, None, b"", 0
        while b"\r\n" not in self.buffer:
            self.buffer += self.socket.recv(65536)
        self.buffer = self.buffer.split(b"\r\n", 1)[1]
        self.command(f'LOGIN "{user}" "{password}"')
        self.command("SELECT INBOX")
        reply, _ = self.command("COMPRESS DEFLATE")
        assert b" OK " in reply
        self.decoder = zlib.decompressobj(-15)
        self.encoder = zlib.compressobj(wbits=-15)

    def command(self, command, prefix=b""):
        self.sequence += 1
        tag = f"runtime{self.sequence:04d}"
        data = f"{tag} {command}\r\n".encode()
        if self.encoder is not None:
            data = self.encoder.compress(data) + self.encoder.flush(zlib.Z_SYNC_FLUSH)
        self.socket.sendall(prefix + data)
        wire = bytearray()
        deadline = time.monotonic() + 5
        pattern = re.compile(
            rb"(?:^|\r\n)" + tag.encode() + rb" (?:OK|NO|BAD)[^\r\n]*\r\n"
        )
        while not pattern.search(self.buffer):
            self.socket.settimeout(max(0.05, deadline - time.monotonic()))
            raw = self.socket.recv(65536)
            assert raw and time.monotonic() < deadline, (
                "compressed IMAP command stopped making progress"
            )
            wire.extend(raw)
            self.buffer += (
                self.decoder.decompress(raw) if self.decoder is not None else raw
            )
        match = pattern.search(self.buffer)
        reply, self.buffer = self.buffer[: match.end()], self.buffer[match.end() :]
        return reply, bytes(wire)

    def close(self):
        self.socket.close()


def compression_reset_probe(
    listener_port, user, password, expected_body, context=None, progress_probe=True
):
    client = CompressedImap(listener_port, user, password, context)
    try:
        # Empty stored blocks produce no output and used to trigger recursive
        # input handling. The following command must still make progress.
        response, _ = client.command(
            "NOOP", prefix=b"\x00\x00\x00\xff\xff" * 4096 if progress_probe else b""
        )
        assert b" OK " in response
        client.command("FETCH 1 (BODY.PEEK[])")
        response, wire = client.command("FETCH 1 (BODY.PEEK[])")
        assert expected_body in response
        candidates = [wire]
        marker = b"\x00\x00\xff\xff"
        # Account only for a previous command's trailing flush bytes arriving
        # with this frame. A marker alone is never accepted as reset evidence.
        for offset in range(min(64, len(wire))):
            if wire[offset : offset + 4] == marker:
                candidates.append(wire[offset + 4 :])
        independent = False
        for candidate in candidates:
            try:
                inflated = zlib.decompressobj(-15).decompress(candidate, 1024 * 1024)
            except zlib.error:
                continue
            if expected_body in inflated and re.search(rb"runtime\d+ OK ", inflated):
                independent = True
                break
        return independent
    finally:
        client.close()


def legacy_storage(root, mailroot, user, password, children, seed=True, label="legacy"):
    old = root / label
    old.mkdir()
    old.chmod(0o755)
    legacy_port = port()
    passwords = old / "users"
    passwords.write_text(f"{user}:{encrypt_password(password)}\n")
    passwords.chmod(0o644)
    config = old / "dovecot.conf"
    config.write_text(f"""base_dir = {old}/run
state_dir = {old}/state
instance_name = isolated-{label}-storage
log_path = {old}/dovecot.log
info_log_path = {old}/dovecot.log
protocols = imap
listen = 127.0.0.1
ssl = no
disable_plaintext_auth = no
mail_uid = vmail
mail_gid = vmail
mail_location = maildir:{mailroot}/%u
mail_plugins = zlib
protocol imap {{
  mail_plugins = $mail_plugins imap_zlib
}}
plugin {{
  zlib_save = gz
}}
passdb {{
  driver = passwd-file
  args = {passwords}
}}
userdb {{
  driver = static
  args = uid=vmail gid=vmail home={mailroot}/%u allow_all_users=yes
}}
service imap-login {{
  inet_listener imap {{
    address = 127.0.0.1
    port = {legacy_port}
  }}
  inet_listener imaps {{
    port = 0
  }}
}}
""")
    subprocess.run(
        ["doveconf", "-c", str(config), "-n"], check=True, stdout=subprocess.DEVNULL
    )
    log = (old / "process.log").open("wb")
    process = subprocess.Popen(
        ["/usr/sbin/dovecot", "-F", "-c", str(config)],
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    children.append(process)
    wait(lambda: (old / "run/master.pid").exists() and listening(legacy_port))
    probe_body = None
    with imaplib.IMAP4("127.0.0.1", legacy_port, timeout=10) as client:
        assert client.login(user, password)[0] == "OK"
        if seed:
            probe_body = base64.b64encode(secrets.token_bytes(6144))
            assert (
                client.append(
                    "INBOX", "(\\Seen)", None, message("legacy-one", body=probe_body)
                )[0]
                == "OK"
            )
            assert (
                client.append(
                    "INBOX", None, None, message("legacy-two", f"<legacy-one@{DOMAIN}>")
                )[0]
                == "OK"
            )
        assert client.select("INBOX")[0] == "OK"
        assert client.thread("REFERENCES", "UTF-8", "ALL")[0] == "OK"
        before = mailbox_snapshot(client)
    if seed:
        old_reset = compression_reset_probe(
            legacy_port, user, password, probe_body, progress_probe=False
        )
        assert old_reset is False, (
            "old control did not demonstrate dictionary reuse; reset probe is insensitive"
        )
    stop(process)
    thread_path = mailroot / user / "dovecot.index.thread"
    assert thread_path.read_bytes()[0] == 1, (
        "fixture must originate from real 2.3 CRC32 thread storage"
    )
    return before, thread_path, probe_body


def main():
    assert os.geteuid() == 0 and os.environ.get("CHATMAIL_ISOLATED_LAB") == "1"
    assert (PREFIX / "sbin/dovecot").exists()
    output = Path(os.environ.get("ARTIFACT_DIR", "/artifacts/runtime24"))
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="runtime24-"))
    root.chmod(0o755)
    children, handles, checks = [], [], []
    mailroot = root / "mail"
    mailroot.mkdir()
    os.chown(mailroot, 5000, 5000)
    mailroot.chmod(0o700)
    config_path = root / "chatmail.ini"
    http_port, imaps_port, push_port = port(), port(), port()
    write_initial_config(
        config_path,
        DOMAIN,
        {
            "mailboxes_dir": str(mailroot),
            "doveauth_http_port": str(http_port),
            "max_load_1m": "100000",
            "min_available_memory": "0M",
            "min_free_disk_space": "0M",
        },
    )
    os.chown(config_path, 0, 5000)
    config_path.chmod(0o640)
    config = read_config(config_path)
    auth_secret, standard_secret, shadow_secret = (
        secrets.token_hex(24) for _ in range(3)
    )
    sensitive_values = [auth_secret, standard_secret, shadow_secret]

    def scrub(content):
        for value in sensitive_values:
            content = content.replace(value, "[synthetic-secret-redacted]")
        return re.sub(
            r"\{SHA512-CRYPT\}\$6\$[^\s'\"]+", "[synthetic-hash-redacted]", content
        )

    legacy_user = f"legacy007@{DOMAIN}"
    legacy_dir = mailroot / legacy_user
    legacy_dir.mkdir()
    (legacy_dir / "password").write_text(encrypt_password(auth_secret))
    os.chown(legacy_dir, 5000, 5000)
    os.chown(legacy_dir / "password", 5000, 5000)
    (legacy_dir / "password").chmod(0o600)
    push = ThreadingHTTPServer(("127.0.0.1", push_port), PushHandler)
    push.lock, push.attempts, push.completed, push.invalid, push.failing = (
        threading.Lock(),
        [],
        [],
        set(),
        False,
    )
    threading.Thread(target=push.serve_forever, daemon=True).start()
    try:
        version = subprocess.check_output(
            [str(PREFIX / "sbin/dovecot"), "--version"], text=True
        ).strip()
        assert version.split()[0] == PROFILE["version"]
        relay_oid = subprocess.check_output(
            [
                "git",
                "-c",
                f"safe.directory={RELAY}",
                "-C",
                str(RELAY),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip()
        assert re.fullmatch(r"[0-9a-f]{40}", relay_oid)
        if os.environ.get("EXPECTED_RELAY_OID"):
            assert relay_oid == os.environ["EXPECTED_RELAY_OID"], (
                "runtime fixture relay OID differs from the selected integration source"
            )
        for program in ("sbin/dovecot", "bin/doveconf", "bin/doveadm"):
            linkage = subprocess.check_output(["ldd", str(PREFIX / program)], text=True)
            assert "/usr/lib64/dovecot" not in linkage and "not found" not in linkage
            assert all(
                str(PREFIX) + "/" in line
                for line in linkage.splitlines()
                if "libdovecot" in line
            )
        checks.append(
            "exact private executable identity and coherent runtime linker namespace"
        )
        before, thread_path, probe_body = legacy_storage(
            root, mailroot, legacy_user, auth_secret, children
        )
        checks.append("real 2.3 storage fixture with UID/flags/CRC32 thread index")
        backup = root / "prewrite-recovery"
        shutil.copytree(mailroot, backup, symlinks=True)
        native = root / "native"
        native.mkdir()
        native.chmod(0o755)
        services = root / "services"
        services.mkdir()
        os.chown(services, 5000, 5000)
        services.chmod(0o750)
        paths = Runtime24Paths(
            version=PROFILE["version"],
            prefix=str(PREFIX),
            config_dir=str(native),
            run_dir=str(native / "run"),
            state_dir=str(native / "state"),
            standard_users=str(native / "standard-users"),
            metadata_socket=str(services / "metadata.socket"),
            lastlogin_socket=str(services / "lastlogin.socket"),
            auth_socket=str(native / "postfix-auth"),
            lmtp_socket=str(native / "lmtp"),
            ssl_cert=str(native / "cert.pem"),
            ssl_key=str(native / "key.pem"),
            postfix_user="root",
            postfix_group="root",
            listen_address="127.0.0.1",
            imaps_port=imaps_port,
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1,DNS:localhost",
                "-keyout",
                paths.ssl_key,
                "-out",
                paths.ssl_cert,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        Path(paths.ssl_key).chmod(0o600)
        standard_user = f"static004@{DOMAIN}"
        standard_dir = mailroot / standard_user
        standard_dir.mkdir()
        (standard_dir / "password").write_text(encrypt_password(shadow_secret))
        os.chown(standard_dir, 5000, 5000)
        os.chown(standard_dir / "password", 5000, 5000)
        Path(paths.standard_users).write_text(
            f"{standard_user}:{encrypt_password(standard_secret)}:5000:5000::{standard_dir}::\n"
        )
        os.chown(paths.standard_users, 0, 5000)
        Path(paths.standard_users).chmod(0o640)
        rendered = render(config, paths)
        for name, content in rendered.items():
            (native / name).write_text(content)
        shutil.copy2(
            ROOT / "tests/fixtures/push_notification.lua",
            native / "push_notification.lua",
        )
        with (native / "dovecot.conf").open("a") as conf:
            conf.write(
                f"\nlog_path = {native}/dovecot.log\ninfo_log_path = {native}/dovecot.log\n"
            )
        subprocess.run(
            [str(PREFIX / "bin/doveconf"), "-c", str(native / "dovecot.conf"), "-n"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        checks.append(
            "version-specific config parse with storage 2.4.5 and unchanged quota/TLS policy"
        )

        def service(name):
            log = (root / f"{name}.log").open("ab")
            handles.append(log)
            command = [
                sys.executable,
                str(ROOT / "tests/runtime24_services.py"),
                name,
                "--config",
                str(config_path),
            ]
            if name == "doveauth":
                command += ["--nocreate-file", str(root / "nocreate")]
            else:
                command += [
                    "--socket",
                    paths.metadata_socket
                    if name == "metadata"
                    else paths.lastlogin_socket,
                ]
            if name == "metadata":
                command += ["--notify-url", f"http://127.0.0.1:{push_port}/notify"]
            environment = {
                "PATH": os.environ["PATH"],
                "PYTHONPATH": f"{RELAY}/chatmaild/src:{RELAY}/cmdeploy/src",
                "CHATMAIL_ISOLATED_LAB": "1",
                "NO_PROXY": "127.0.0.1,localhost",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            process = subprocess.Popen(
                command,
                env=environment,
                user=5000,
                group=5000,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            children.append(process)
            return process

        auth = service("doveauth")
        service("metadata")
        service("lastlogin")
        wait(
            lambda: (
                Path(paths.metadata_socket).exists()
                and Path(paths.lastlogin_socket).exists()
            )
        )
        log = (native / "process.log").open("ab")
        handles.append(log)
        dovecot = subprocess.Popen(
            [str(PREFIX / "sbin/dovecot"), "-F", "-c", str(native / "dovecot.conf")],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        children.append(dovecot)
        wait(
            lambda: (
                Path(paths.lmtp_socket).exists()
                and listening(imaps_port)
                and listening(http_port)
            )
        )
        context = ssl.create_default_context(cafile=paths.ssl_cert)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        source_sequence, source_lock = 0, threading.Lock()

        def login(user, secret):
            nonlocal source_sequence
            with source_lock:
                source_sequence += 1
                assert source_sequence < 255
                source_address = f"127.0.1.{source_sequence}"
            try:
                client = FixtureImap(
                    "127.0.0.1",
                    imaps_port,
                    ssl_context=context,
                    timeout=10,
                    source_address=source_address,
                )
            except imaplib.IMAP4.error:
                # Greeting/capabilities precede authentication and contain no
                # submitted password or token. Capture only a bounded line.
                with socket.create_connection(
                    ("127.0.0.1", imaps_port), timeout=5
                ) as raw:
                    with context.wrap_socket(
                        raw, server_hostname="127.0.0.1"
                    ) as secure:
                        greeting = secure.recv(4096).decode(errors="replace")
                (root / "preauth-greeting.log").write_text(scrub(greeting))
                raise
            try:
                assert client.login(user, secret)[0] == "OK"
                assert client.sock.version() == "TLSv1.3"
                return client
            except BaseException:
                client.shutdown()
                raise

        with login(legacy_user, auth_secret) as client:
            assert mailbox_snapshot(client) == before
            assert client.thread("REFERENCES", "UTF-8", "ALL")[0] == "OK"
        assert thread_path.read_bytes()[0] == 2
        checks.append(
            "2.3 to 2.4 UID/UIDVALIDITY/flags/bytes preserved and keyed v2 thread index rebuilt"
        )
        assert compression_reset_probe(
            imaps_port, legacy_user, auth_secret, probe_body, context
        )
        checks.append(
            "DEFLATE empty-input progress and independent per-command output reset, sensitive against 2.3 control"
        )
        users = (f"member001@{DOMAIN}", f"member002@{DOMAIN}")
        for user in users:
            with login(user, auth_secret):
                pass
        with login(standard_user, standard_secret):
            pass
        for user, secret in (
            (users[0], shadow_secret),
            (standard_user, shadow_secret),
            (f"foreignaccount@foreign.test", auth_secret),
        ):
            try:
                with login(user, secret):
                    pass
            except imaplib.IMAP4.error:
                pass
            else:
                raise AssertionError(
                    "wrong/foreign/standard-shadow credentials accepted"
                )
        checks.append(
            "real Lua/HTTP new-user auth, wrong passwords, foreign-domain and standard-user precedence"
        )
        policy = Path(paths.standard_users)
        policy_bytes = policy.read_bytes()
        for policy_index, mode in enumerate(("missing", "unreadable", "malformed"), 1):
            if mode == "missing":
                policy.rename(native / "standard-users.saved")
            elif mode == "unreadable":
                policy.chmod(0o000)
            else:
                policy.write_text("truncated-policy-row\n")
            refused_user = f"policy{policy_index:03d}@{DOMAIN}"
            refusal_started = time.monotonic()
            try:
                with login(refused_user, auth_secret):
                    pass
            except imaplib.IMAP4.error:
                pass
            else:
                raise AssertionError(
                    "unavailable standard-user policy allowed provisioning"
                )
            assert not (mailroot / refused_user).exists()
            assert time.monotonic() - refusal_started < 8, (
                "policy denial did not complete within bounded auth budget"
            )
            if mode == "missing":
                (native / "standard-users.saved").rename(policy)
            policy.chmod(0o640)
            policy.write_bytes(policy_bytes)
        checks.append(
            "missing, unreadable and malformed standard-user policy fails closed before provisioning"
        )
        race_user = f"racer0003@{DOMAIN}"

        def racing(_):
            with login(race_user, auth_secret):
                pass

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(racing, range(4)))
        assert (mailroot / race_user / "password").is_file()
        checks.append("concurrent first-login provisioning")
        (root / "nocreate").touch()
        try:
            with login(f"blocked06@{DOMAIN}", auth_secret):
                pass
        except imaplib.IMAP4.error:
            pass
        else:
            raise AssertionError("creation policy bypassed")
        (root / "nocreate").unlink()
        checks.append("first-use registration policy")
        stop(auth)
        started = time.monotonic()
        try:
            with login(f"backend05@{DOMAIN}", auth_secret):
                pass
        except imaplib.IMAP4.error:
            pass
        else:
            raise AssertionError("unavailable auth backend accepted unknown user")
        assert time.monotonic() - started < 8
        with login(users[0], auth_secret):
            pass
        auth = service("doveauth")
        wait(lambda: listening(http_port))
        assert "invalid error return value" not in (native / "dovecot.log").read_text()
        checks.append(
            "auth backend failure bounded; existing-account login remains available"
        )

        # Real metadata persistence and the actual separate notification worker
        # are exercised with opaque synthetic tokens and a loopback-only mock.
        tokens = [secrets.token_hex(18).encode() for _ in range(4)]
        sensitive_values.extend(token.decode() for token in tokens)
        push.invalid.add(tokens[2])
        legacy_metadata = mailroot / users[0] / "metadata.json"
        legacy_metadata.write_text(
            json.dumps({"devicetoken": [token.decode() for token in tokens[:3]]})
        )
        os.chown(legacy_metadata, 5000, 5000)
        legacy_metadata.chmod(0o600)
        with login(users[1], auth_secret) as client:
            assert (
                client._simple_command(
                    "SETMETADATA",
                    "INBOX",
                    f'(/private/devicetoken "{tokens[3].decode()}")',
                )[0]
                == "OK"
            )
        assert lmtp(paths.lmtp_socket, users[0]).startswith("250")
        wait(lambda: all(token in push.completed for token in tokens[:2]))
        wait(
            lambda: (
                tokens[2].decode()
                not in json.loads(legacy_metadata.read_text())["devicetoken"]
            )
        )
        assert isinstance(json.loads(legacy_metadata.read_text())["devicetoken"], dict)
        checks.append(
            "legacy token-list migration, multiple devices, real notifier handoff and invalid-token removal"
        )
        completed = len(push.completed)
        self_message = message("self-message").replace(
            f"sender@{DOMAIN}".encode(), users[0].encode()
        )
        assert lmtp(
            paths.lmtp_socket, users[0], sender=users[0], payload=self_message
        ).startswith("250")
        time.sleep(0.3)
        assert len(push.completed) == completed
        checks.append("deployed Lua MessageNew hook preserves self-message suppression")
        before_counts = {token: push.completed.count(token) for token in tokens}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(
                executor.map(lambda user: lmtp(paths.lmtp_socket, user), users)
            )
        assert all(reply.startswith("250") for reply in replies)
        wait(
            lambda: all(
                push.completed.count(tokens[index]) == before_counts[tokens[index]] + 1
                for index in (0, 1, 3)
            )
        )
        checks.append("concurrent LMTP deliveries retain mailbox/device isolation")
        push.failing = True
        successful_before = push.completed.count(tokens[3])
        assert lmtp(paths.lmtp_socket, users[1]).startswith("250")
        pending = mailroot / "pending_notifications"
        wait(
            lambda: any(
                path.is_file() and not path.name.endswith(".tmp")
                for path in pending.iterdir()
            )
        )
        attempts_before = len(push.attempts)
        push.failing = False
        wait(
            lambda: (
                push.completed.count(tokens[3]) == successful_before + 1
                and not list(pending.iterdir())
            ),
            seconds=12,
        )
        assert len(push.attempts) >= attempts_before
        checks.append(
            "notification HTTP failure retains durable queue and recovers through real worker retries"
        )

        with login(users[0], auth_secret) as client:
            assert client.select("INBOX")[0] == "OK"
            quota_kind, quota_data = client.getquotaroot("INBOX")
            assert quota_kind == "OK" and b"1024000" in b" ".join(
                part for part in quota_data[1] if part
            )
            started = time.monotonic()
            assert client.list('""', "*" * 128 + "unmatched-suffix")[0] == "OK"
            assert time.monotonic() - started < 3
            assert client.noop()[0] == "OK"
            imaplib.Commands.setdefault("COMPRESS", ("AUTH", "SELECTED"))
            try:
                result, _ = client._simple_command("COMPRESS", "ZSTD")
            except imaplib.IMAP4.error:
                result = "BAD"
            assert result in ("NO", "BAD")
            assert client.noop()[0] == "OK"
        checks.append(
            "real IMAP quota, bounded adversarial LIST, unsupported compression rejection and continued progress"
        )
        password_mtime = int((mailroot / users[0] / "password").stat().st_mtime)
        assert password_mtime == int(time.time()) // 86400 * 86400
        checks.append(
            "real named last-login dictionary updates the existing password-file timestamp contract"
        )
        # A bounded References workload exercises the actual thread parser and
        # v2 keyed strmap path, independently of the native unit-suite result.
        references = " ".join(f"<reference-{index}@{DOMAIN}>" for index in range(1024))
        assert lmtp(
            paths.lmtp_socket, users[1], payload=message("many-references", references)
        ).startswith("250")
        with login(users[1], auth_secret) as client:
            assert client.select("INBOX")[0] == "OK"
            started = time.monotonic()
            assert client.thread("REFERENCES", "UTF-8", "ALL")[0] == "OK"
            assert time.monotonic() - started < 3
        assert (mailroot / users[1] / "dovecot.index.thread").read_bytes()[0] == 2
        checks.append("bounded References threading and keyed v2 index on new mail")
        delivered_before = {
            path: digest(path.read_bytes())
            for directory in ("new", "cur")
            for path in (mailroot / users[1] / directory).glob("*")
        }
        oversized = message("oversized", body=(b"q" * 1000 + b"\r\n") * 31500)
        # Native SMTP allows 1 MiB excess while draining DATA after 552. Keep
        # this message above policy and below the independent disconnect cap.
        assert 31457280 < len(oversized) < 31457280 + 1024 * 1024
        assert lmtp(paths.lmtp_socket, users[1], payload=oversized).startswith("552")
        delivered_after = {
            path: digest(path.read_bytes())
            for directory in ("new", "cur")
            for path in (mailroot / users[1] / directory).glob("*")
        }
        assert delivered_after == delivered_before, (
            "rejected oversized DATA was delivered or changed existing messages"
        )
        assert "invalid error return value" not in (native / "dovecot.log").read_text()
        checks.append("30 MiB message limit is enforced by real LMTP quota handling")
        gzip_paths = list((mailroot / users[0] / "new").glob("*")) + list(
            (mailroot / users[0] / "cur").glob("*")
        )
        assert gzip_paths and all(
            BytesParser().parsebytes(gzip.decompress(path.read_bytes()))["Subject"]
            == "isolated runtime qualification"
            for path in gzip_paths
        )
        accepted_hashes = {path: digest(path.read_bytes()) for path in gzip_paths}
        checks.append("existing and new gzip-stored messages remain readable")
        stop(dovecot)
        for path in [backup, *backup.rglob("*")]:
            os.chown(path, 5000, 5000, follow_symlinks=False)
        restored, _, _ = legacy_storage(
            root,
            backup,
            legacy_user,
            auth_secret,
            children,
            seed=False,
            label="recovery",
        )
        assert restored == before
        assert all(
            path.is_file() and digest(path.read_bytes()) == expected
            for path, expected in accepted_hashes.items()
        )
        checks.append(
            "separate pre-write recovery copy restores under 2.3 without rewinding newly accepted mail"
        )
        receipt = {
            "passed": len(checks),
            "checks": checks,
            "synthetic_only": True,
            "external_network": False,
            "production_ready": False,
            "profile": PROFILE["profile"],
            "relay_oid": relay_oid,
            "relay_profile_sources": {
                name: digest((RELAY / name).read_bytes())
                for name in (
                    "cmdeploy/src/cmdeploy/runtime24.py",
                    "cmdeploy/src/cmdeploy/dovecot/dovecot24.conf.j2",
                    "cmdeploy/src/cmdeploy/dovecot/auth24.lua.j2",
                    "chatmaild/src/chatmaild/doveauth.py",
                    "chatmaild/src/chatmaild/metadata.py",
                    "chatmaild/src/chatmaild/notifier.py",
                    "chatmaild/src/chatmaild/lastlogin.py",
                )
            },
            "contracts": {
                name: True
                for name in (
                    "authentication",
                    "notification",
                    "metadata",
                    "storage_transition",
                    "compression_reset",
                    "quota",
                    "standard_users",
                )
            },
            "build_manifest_sha256": digest((output / "manifest.json").read_bytes())
            if (output / "manifest.json").exists()
            else None,
            "harness_sha256": digest(Path(__file__).read_bytes()),
            "rendered_config_sha256": digest((native / "dovecot.conf").read_bytes()),
            "rendered_auth_sha256": digest((native / "auth.lua").read_bytes()),
            "storage_transition": {
                "uid_and_bytes_preserved": True,
                "thread_format_before": 1,
                "thread_format_after": 2,
                "prewrite_restore_qualified": True,
                "new_mail_preserved": True,
                "postwrite_downgrade": "not attempted or qualified; reconcile new mail before production rollback",
            },
        }
        (output / "runtime24-regression.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(json.dumps(receipt, sort_keys=True))
    except Exception as error:
        (output / "runtime24-regression.json").write_text(
            json.dumps(
                {
                    "passed": len(checks),
                    "checks": checks,
                    "failed": 1,
                    "error": scrub(f"{type(error).__name__}: {error}"),
                    "synthetic_only": True,
                },
                indent=2,
            )
            + "\n"
        )
        raise
    finally:
        for process in reversed(children):
            stop(process)
        push.shutdown()
        push.server_close()
        for handle in handles:
            handle.close()
        # No private TLS key, password hash, token file or message body is copied.
        for path in root.rglob("*.log"):
            (output / f"runtime24-{path.parent.name}-{path.name}").write_text(
                scrub(path.read_text(errors="replace"))
            )


if __name__ == "__main__":
    main()
