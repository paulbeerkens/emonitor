#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo: sudo ./deployment/install-service.sh" >&2
  exit 1
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
service_user="${1:-${SUDO_USER:-}}"

if [[ -z "$service_user" || "$service_user" == "root" ]]; then
  echo "Could not determine the non-root account that should run EMonitor." >&2
  echo "Run with sudo, or provide the account: sudo $0 <username>" >&2
  exit 1
fi

if ! id "$service_user" >/dev/null 2>&1; then
  echo "User '$service_user' does not exist." >&2
  exit 1
fi

service_group="$(id -gn "$service_user")"
template="$project_dir/deployment/emonitor.service.template"
service_file="/etc/systemd/system/emonitor.service"

if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
  echo "Python environment not found. Run ./env/install.sh first." >&2
  exit 1
fi

if [[ ! -f "$project_dir/.env" ]]; then
  echo "Configuration not found. Copy .env.example to .env and edit it first." >&2
  exit 1
fi

mkdir -p "$project_dir/db" "$project_dir/log"
chown -R "$service_user:$service_group" "$project_dir/db" "$project_dir/log"

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

escaped_user="$(escape_sed_replacement "$service_user")"
escaped_group="$(escape_sed_replacement "$service_group")"
escaped_project="$(escape_sed_replacement "$project_dir")"
temporary_service="$(mktemp)"
trap 'rm -f "$temporary_service"' EXIT

sed \
  -e "s|__SERVICE_USER__|$escaped_user|g" \
  -e "s|__SERVICE_GROUP__|$escaped_group|g" \
  -e "s|__PROJECT_DIR__|$escaped_project|g" \
  "$template" > "$temporary_service"

install -m 0644 "$temporary_service" "$service_file"
systemctl daemon-reload
systemctl enable emonitor.service
systemctl restart emonitor.service

echo "EMonitor is installed and running as $service_user."
echo "View its status with: systemctl status emonitor"
echo "Follow its console log with: journalctl -u emonitor -f"
