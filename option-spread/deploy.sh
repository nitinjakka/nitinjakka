#!/usr/bin/env bash
# Deploy spread_cycler to the jump server under /opt/option_spread.
# Usage:  ./deploy.sh [user@host]
set -euo pipefail

TARGET="${1:-root@74.208.194.214}"
DEST=/opt/option_spread
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Deploying to ${TARGET}:${DEST}"

ssh "$TARGET" "mkdir -p ${DEST}/logs"

# Never ship the real .env or local state.
scp "$HERE/spread_cycler.py" \
    "$HERE/spread_cycler.env.example" \
    "$HERE/requirements.txt" \
    "$HERE/README.md" \
    "$HERE/option-spread.service" \
    "$HERE/option-spread.timer" \
    "$TARGET:${DEST}/"

ssh "$TARGET" bash -s <<EOF
set -euo pipefail
cd ${DEST}
if [ ! -d .venv ]; then
  echo "==> Creating venv"
  python3 -m venv .venv
fi
echo "==> Installing dependencies"
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt
if [ ! -f spread_cycler.env ]; then
  cp spread_cycler.env.example spread_cycler.env
  chmod 600 spread_cycler.env
  echo "==> Created spread_cycler.env from the example -- FILL IN CREDENTIALS"
fi
echo "==> Verifying import (paper mode, no login)"
./.venv/bin/python -c "import ast,sys; ast.parse(open('spread_cycler.py').read()); print('   syntax OK')"
echo "==> Done. ${DEST} is ready."
EOF

cat <<'NOTE'

Next steps on the server:
  1. nano /opt/option_spread/spread_cycler.env      # credentials, LIVE=0
  2. cd /opt/option_spread && ./.venv/bin/python spread_cycler.py
  3. Review trades.csv before ever setting LIVE=1
NOTE
