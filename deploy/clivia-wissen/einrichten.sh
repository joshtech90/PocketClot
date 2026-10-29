#!/bin/bash
# Auf web im hochgeladenen Ordner: sudo bash einrichten.sh
set -euo pipefail
CLIVIA_PAKET=$(cd -- "$(dirname -- "$0")" && pwd -P)
export PYTHONDONTWRITEBYTECODE=1
exec /usr/bin/env python3 "$CLIVIA_PAKET/installation.py" einrichten "$CLIVIA_PAKET"
