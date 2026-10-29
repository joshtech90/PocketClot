#!/bin/bash
# sudo bash zuruecknehmen.sh /var/backups/pocketclot-clivia/<Zeitstempel>
set -euo pipefail
CLIVIA_PAKET=$(cd -- "$(dirname -- "$0")" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
exec /usr/bin/env python3 "$CLIVIA_PAKET/installation.py" zuruecknehmen "${1:?Backupordner angeben}"
