#!/usr/bin/env bash
# collect_batch.sh — 複数企業の実データ(EDINET + プレスリリース)をまとめて収集する。
# 企業リストは companies.csv (列: company,edinet_code,press_url) で管理。
# 使い方:
#   export EDINET_API_KEY="発行されたキー"
#   ./collect_batch.sh
# Windows (PowerShell) の場合はこのスクリプトの代わりに:
#   $env:EDINET_API_KEY="発行されたキー"
#   python collect.py --batch companies.csv
set -e
cd "$(dirname "$0")"

if [ -z "$EDINET_API_KEY" ]; then
  echo "[ERROR] EDINET_API_KEY が設定されていません"
  exit 1
fi

python collect.py --batch companies.csv
python engine.py
