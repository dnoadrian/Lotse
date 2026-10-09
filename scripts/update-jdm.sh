#!/usr/bin/env bash
# Aktualisiert den mitgelieferten JustDeleteMe-Datensatz aus https://github.com/jdm-contrib/jdm
set -euo pipefail
cd "$(dirname "$0")/.."

target="backend/app/data/jdm"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --depth 1 https://github.com/jdm-contrib/jdm.git "$tmp/jdm"
python3 -I -c "
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
assert isinstance(d, list) and len(d) > 1000, 'unerwartete Struktur'
for e in d:
    assert {'name', 'url', 'difficulty', 'domains'} <= e.keys(), e.get('name')
print(len(d), 'Einträge geprüft')
" "$tmp/jdm/_data/sites.json"

cp "$tmp/jdm/_data/sites.json" "$target/sites.json"
cp "$tmp/jdm/LICENSE" "$target/LICENSE"
git -C "$tmp/jdm" log -1 --format='{"commit": "%H", "date": "%cs", "source": "https://github.com/jdm-contrib/jdm"}' > "$target/VERSION.json"
echo "Aktualisiert auf $(cat "$target/VERSION.json")"
echo "Jetzt testen (cd backend && pytest tests/test_jdm.py) und neu bauen (docker compose up -d --build)."
