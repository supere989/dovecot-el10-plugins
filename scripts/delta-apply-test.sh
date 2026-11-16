#!/usr/bin/env bash
# The historical script installed packages, restarted production and sent mail.
# Those operations require a separately reviewed rollout, never a smoke-test default.
echo 'Refused: no production install/restart/message test is provided.' >&2
echo 'Run scripts/lab-test.sh only inside the isolated project AlmaLinux devbox.' >&2
exit 2
