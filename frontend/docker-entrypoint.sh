#!/bin/sh
set -e

LOCKFILE_HASH="$(sha256sum package-lock.json | awk '{print $1}')"
INSTALLED_HASH="$(cat node_modules/.deps-hash 2>/dev/null || true)"

if [ ! -d node_modules ] || [ "$LOCKFILE_HASH" != "$INSTALLED_HASH" ]; then
  npm ci
  mkdir -p node_modules
  printf "%s" "$LOCKFILE_HASH" > node_modules/.deps-hash
fi

exec "$@"
