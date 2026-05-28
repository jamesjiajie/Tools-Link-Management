#!/bin/bash

set -e

cd "$(dirname "$0")"

URL="http://localhost:4173"

if command -v curl >/dev/null 2>&1 && curl -fsS "$URL" >/dev/null 2>&1; then
  open "$URL"
  echo "Portal Hub is already running at $URL"
  exit 0
fi

(
  sleep 1
  open "$URL"
) &

echo "Starting Portal Hub at $URL"
exec python3 server.py
