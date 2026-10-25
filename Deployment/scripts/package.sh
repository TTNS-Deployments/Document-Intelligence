#!/usr/bin/env bash
# Builds the deployable web app package: build/webapp.zip
#
#   Deployment/scripts/package.sh            app code, docintel package, Config/, sample invoices, static files
#   Deployment/scripts/package.sh --vendor   the same, plus every Python library in .packages (no remote build needed)
#
# The package runs from a read-only mount on App Service (WEBSITE_RUN_FROM_PACKAGE), so the static files are
# collected into it here. With --vendor, Linux x64 / Python 3.12 wheels are downloaded into .packages and the
# app runs with PYTHONPATH=/home/site/wwwroot/.packages. Uses tar and Python (no rsync, no zip needed), so it runs
# in Azure Cloud Shell, a Codespace and CI.
set -euo pipefail

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }
VENDOR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vendor) VENDOR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option $1 (see --help)" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build"
STAGE="$BUILD/webapp"
PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m pip --version >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
[[ -n "$PY" ]] || { echo "python3 is required" >&2; exit 1; }
PY="$(command -v "$PY")"
if [[ "$PY" != /* ]]; then PY="$(cd "$(dirname "$PY")" && pwd)/$(basename "$PY")"; fi  # the static step runs elsewhere
"$PY" -m pip --version >/dev/null 2>&1 || { echo "$PY has no pip; set PYTHON to an interpreter with pip" >&2; exit 1; }
PIP_TARGET_FLAGS=(--quiet --disable-pip-version-check --only-binary=:all: --implementation cp --python-version 3.12
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 --upgrade)

rm -rf "$BUILD" && mkdir -p "$STAGE"

echo "==> Staging the web app"
tar -C "$ROOT/Code/webapp" --exclude='__pycache__' --exclude='*.pyc' --exclude='staticfiles' --exclude='tests' \
    -cf - . | tar -C "$STAGE" -xf -
tar -C "$ROOT/Code/core" --exclude='__pycache__' --exclude='*.pyc' -cf - docintel | tar -C "$STAGE" -xf -
tar -C "$ROOT" -cf - Config | tar -C "$STAGE" -xf -
mkdir -p "$STAGE/Data"
tar -C "$ROOT/Data" --exclude='generate.py' -cf - sample_invoices | tar -C "$STAGE/Data" -xf -

if [[ $VENDOR -eq 1 ]]; then
  echo "==> Downloading Python libraries for Linux / Python 3.12 into .packages (takes a minute or two)"
  "$PY" -m pip install "${PIP_TARGET_FLAGS[@]}" --target "$STAGE/.packages" -r "$STAGE/requirements.txt"
  STATIC_PATH="$STAGE/.packages"
else
  "$PY" -c "import django" 2>/dev/null || { echo "Django is not installed for $PY: run 'make setup' or use --vendor" >&2; exit 1; }
  STATIC_PATH=""
fi

echo "==> Collecting static files into the package"
(cd "$STAGE" && PYTHONPATH="$STATIC_PATH" DOCINTEL_MODE=local DJANGO_DEBUG=false "$PY" manage.py collectstatic --noinput -v 0)

echo "==> Writing build/webapp.zip"
"$PY" - "$STAGE" "$BUILD/webapp.zip" <<'PYZIP'
import os, sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for folder, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            z.write(path, os.path.relpath(path, src))
PYZIP
echo "Built $BUILD/webapp.zip ($(du -h "$BUILD/webapp.zip" | cut -f1))"
