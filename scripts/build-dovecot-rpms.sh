#!/usr/bin/env bash
echo 'Refused: this repository builds an exact-ABI addon, not replacement core packages.' >&2
echo 'Use the signed AlmaLinux runtime RPMs retained by scripts/entrypoint.sh.' >&2
exit 2
