#!/usr/bin/env python3
"""Launch real relay services with strictly local fixture-only substitutions."""

import argparse
import os
import sys
from urllib.parse import urlsplit


def main():
    if os.environ.get("CHATMAIL_ISOLATED_LAB") != "1":
        raise SystemExit("isolated lab environment required")
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("doveauth", "metadata", "lastlogin"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket")
    parser.add_argument("--notify-url")
    parser.add_argument("--nocreate-file")
    args = parser.parse_args()
    if args.service == "doveauth":
        from chatmaild import doveauth

        doveauth.NOCREATE_FILE = args.nocreate_file
        sys.argv = ["fixture-doveauth", args.config]
        doveauth.main()
    elif args.service == "metadata":
        endpoint = urlsplit(args.notify_url)
        if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1":
            raise SystemExit("fixture notification endpoint must be local loopback")
        from chatmaild import metadata
        from chatmaild.notifier import Notifier

        Notifier.URL = args.notify_url
        Notifier.BASE_DELAY = 2.0
        Notifier.DROP_DEADLINE = 30
        Notifier.CONNECTION_TIMEOUT = 2.0
        sys.argv = ["fixture-metadata", args.socket, args.config]
        metadata.main()
    else:
        from chatmaild import lastlogin

        sys.argv = ["fixture-lastlogin", args.socket, args.config]
        lastlogin.main()


if __name__ == "__main__":
    main()
