#!/usr/bin/env python3
"""Real Dovecot/Lua/LMTP seam test against a local chatmail dict-protocol mock.

Only synthetic maildirs and Unix sockets are used. No SMTP transport, production
configuration, account, push token or outbound notification endpoint is loaded.
"""

import concurrent.futures
import gzip
import json
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MetadataHandler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        with self.server.connection_lock:
            self.server.connections.add(self.request)

    def finish(self):
        with self.server.connection_lock:
            self.server.connections.discard(self.request)
        super().finish()

    def handle(self):
        transactions = {}
        while raw := self.rfile.readline():
            message = raw.rstrip(b"\r\n").decode()
            if not message:
                continue
            command, parts = message[0], message[1:].split("\t")
            response = None
            if command == "H":
                pass
            elif command == "L":
                response = "N\n"
            elif command == "I":
                response = "\n"
            elif command == "B":
                transactions[parts[0]] = {
                    "addr": parts[1],
                    "result": "O\n",
                    "events": [],
                }
            elif command == "S":
                transaction = transactions[parts[0]]
                keys = parts[1].split("/")
                if len(keys) == 3 and keys[0] == "priv" and keys[2] == "messagenew":
                    transaction["events"].append(transaction["addr"])
                else:
                    transaction["result"] = "F\n"
            elif command == "C":
                transaction = transactions.pop(parts[0])
                response = transaction["result"]
                if response == "O\n":
                    with self.server.event_lock:
                        self.server.events.extend(transaction["events"])
            else:
                raise AssertionError(f"unexpected dict command {command!r}")
            if response is not None:
                self.wfile.write(response.encode())
                self.wfile.flush()


class MetadataServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, events, lock):
        super().__init__(str(path), MetadataHandler)
        self.events, self.event_lock = events, lock
        self.connections, self.connection_lock = set(), threading.Lock()
        os.chmod(path, 0o777)

    def disconnect_clients(self):
        with self.connection_lock:
            for connection in tuple(self.connections):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


def wait_path(path, process=None):
    for _ in range(200):
        if path.exists():
            return
        if process is not None and process.poll() is not None:
            raise AssertionError(f"Dovecot exited with {process.returncode}")
        time.sleep(0.05)
    raise AssertionError(f"socket did not appear: {path.name}")


def deliver(path, recipient, sender="sender@synthetic.test", body="synthetic delivery"):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(15)
        connection.connect(str(path))
        stream = connection.makefile("rwb", buffering=0)

        def reply():
            lines = []
            while True:
                line = stream.readline().decode()
                if not line:
                    raise AssertionError("LMTP disconnected")
                lines.append(line)
                if len(line) < 4 or line[3] != "-":
                    return lines[-1]

        assert reply().startswith("220")
        for command in (
            "LHLO synthetic.test",
            f"MAIL FROM:<{sender}>",
            f"RCPT TO:<{recipient}>",
        ):
            stream.write((command + "\r\n").encode())
            assert reply().startswith("250"), command
        stream.write(b"DATA\r\n")
        assert reply().startswith("354")
        message = f"From: {sender}\r\nTo: {recipient}\r\nSubject: isolated notification test\r\n\r\n{body}\r\n.\r\n"
        stream.write(message.encode())
        result = reply()
        stream.write(b"QUIT\r\n")
        reply()
        return result


def main():
    assert os.geteuid() == 0, "run as root inside the isolated rootless container"
    assert os.environ.get("CHATMAIL_ISOLATED_LAB") == "1", (
        "explicit lab environment required"
    )
    temporary = Path(tempfile.mkdtemp(prefix="chatmail-lmtp-"))
    # Retain logs/fixtures on failure in the container; never delete arbitrary trees.
    os.chmod(temporary, 0o755)
    for directory in ("run", "state", "mail"):
        (temporary / directory).mkdir()
    os.chown(temporary / "mail", 5000, 5000)
    hook = temporary / "push.lua"
    shutil.copy2(ROOT / "tests/fixtures/push_notification.lua", hook)
    metadata_path, lmtp_path = temporary / "metadata.sock", temporary / "run/lmtp"
    events, event_lock = [], threading.Lock()
    server = MetadataServer(metadata_path, events, event_lock)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = temporary / "dovecot.conf"
    config.write_text(f"""base_dir = {temporary}/run
state_dir = {temporary}/state
instance_name = chatmail-isolated-lab
log_path = {temporary}/dovecot.log
info_log_path = {temporary}/dovecot.log
protocols = lmtp
listen = 127.0.0.1
ssl = no
first_valid_uid = 1000
mail_uid = 5000
mail_gid = 5000
mail_location = maildir:{temporary}/mail/%u
mail_attribute_dict = proxy:{metadata_path}:metadata
mail_plugins = zlib quota
passdb {{
  driver = static
  args = nopassword=yes
}}
userdb {{
  driver = static
  args = uid=5000 gid=5000 home={temporary}/mail/%u allow_all_users=yes
}}
protocol lmtp {{
  mail_plugin_dir = /usr/lib64/dovecot/chatmail-lua
  mail_plugins = $mail_plugins mail_lua notify push_notification push_notification_lua
}}
plugin {{
  push_notification_driver = lua:file={hook}
  zlib_save = gz
  quota = maildir:User quota
  quota_rule = *:storage=1000M
  quota_max_mail_size = 31457280
}}
service lmtp {{
  user = labmail
  unix_listener lmtp {{
    mode = 0666
  }}
}}
""")
    subprocess.run(
        ["doveconf", "-c", str(config), "-n"], check=True, stdout=subprocess.DEVNULL
    )
    process = subprocess.Popen(
        ["dovecot", "-F", "-c", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    results = []
    try:
        wait_path(lmtp_path, process)
        users = ("one@synthetic.test", "two@synthetic.test")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(lambda user: deliver(lmtp_path, user), users))
        assert all(reply.startswith("250") for reply in replies), replies
        for _ in range(100):
            with event_lock:
                if sorted(events) == sorted(users):
                    break
            time.sleep(0.05)
        assert sorted(events) == sorted(users), events
        results.append("incoming notifications and concurrent user isolation")
        assert deliver(lmtp_path, users[0], sender=users[0]).startswith("250")
        time.sleep(0.2)
        assert len(events) == 2, events
        results.append("self-message suppression")
        messages = list((temporary / "mail" / users[0] / "new").iterdir())
        assert len(messages) == 2
        parsed = [
            BytesParser().parsebytes(gzip.decompress(message.read_bytes()))
            for message in messages
        ]
        assert all(
            message["Subject"] == "isolated notification test" for message in parsed
        )
        assert {message["From"] for message in parsed} == {
            "sender@synthetic.test",
            users[0],
        }
        results.append("gzip storage remains readable")
        # A live connection is forcibly closed before unlinking the backend.
        server.shutdown()
        server.disconnect_clients()
        server.server_close()
        metadata_path.unlink()
        started = time.monotonic()
        failure_reply = deliver(lmtp_path, users[1], body="backend unavailable")
        assert time.monotonic() - started < 15
        assert failure_reply[:1] in ("2", "4"), failure_reply
        results.append("backend failure is bounded")
        server = MetadataServer(metadata_path, events, event_lock)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        assert deliver(lmtp_path, users[1], body="backend restored").startswith("250")
        for _ in range(100):
            if events.count(users[1]) >= 2:
                break
            time.sleep(0.05)
        assert events.count(users[1]) == 2, events
        log = (temporary / "dovecot.log").read_text()
        assert any(
            word in log.lower() for word in ("error", "failed", "disconnected")
        ), "backend outage must be audited"
        results.append("backend recovery and failure audit")
        receipt = {
            "passed": len(results),
            "checks": results,
            "external_notifications": 0,
            "synthetic_only": True,
            "fixture_directory": str(temporary),
        }
        output = Path(os.environ.get("ARTIFACT_DIR", "/artifacts"))
        (output / "lmtp-regression.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(json.dumps(receipt, sort_keys=True))
    except Exception as error:
        output = Path(os.environ.get("ARTIFACT_DIR", "/artifacts"))
        receipt = {
            "passed": len(results),
            "checks": results,
            "failed": 1,
            "error": f"{type(error).__name__}: {error}",
            "synthetic_only": True,
        }
        (output / "lmtp-regression.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        if process.returncode not in (0, -15):
            print(process.communicate()[0].decode())
        if (temporary / "dovecot.log").exists():
            print((temporary / "dovecot.log").read_text())
        output = Path(os.environ.get("ARTIFACT_DIR", "/artifacts"))
        shutil.copy2(config, output / f"{temporary.name}.conf")
        if (temporary / "dovecot.log").exists():
            shutil.copy2(temporary / "dovecot.log", output / f"{temporary.name}.log")


if __name__ == "__main__":
    main()
