#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/alessarsolutions}"
FRONTEND_DIR="$APP_DIR/frontend"
PUBLIC_DIR="${PUBLIC_DIR:-$HOME/public_html}"
API_ORIGIN="${VITE_DASHBOARD_URL:-https://api.alessarsolutions.in}"

test -f "$FRONTEND_DIR/package.json" || { echo "Missing $FRONTEND_DIR/package.json" >&2; exit 1; }

home_path="$(realpath -m "$HOME")"
public_path="$(realpath -m "$PUBLIC_DIR")"
case "$public_path" in
  "$home_path"/public_html|"$home_path"/public_html/*) ;;
  *) echo "PUBLIC_DIR must stay inside $HOME/public_html" >&2; exit 1 ;;
esac

cd "$FRONTEND_DIR"
npm ci
VITE_DASHBOARD_URL="$API_ORIGIN" npm run build
mkdir -p "$PUBLIC_DIR"
rsync -a --delete "$FRONTEND_DIR/dist/" "$PUBLIC_DIR/"

echo "Frontend deployed to $PUBLIC_DIR with API origin $API_ORIGIN"
