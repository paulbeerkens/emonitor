#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

mkdir -p db log
echo "Environment ready. Run the collector with: .venv/bin/python main.py"
echo "To install and run it as a systemd service: sudo ./deployment/install-service.sh"
