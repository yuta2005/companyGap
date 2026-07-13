#!/usr/bin/env bash
# collect_batch.sh — 複数企業の実データ(EDINET + プレスリリース)をまとめて収集する。
# 使い方:
#   export EDINET_API_KEY="発行されたキー"
#   ./collect_batch.sh
set -e
cd "$(dirname "$0")"

if [ -z "$EDINET_API_KEY" ]; then
  echo "[ERROR] EDINET_API_KEY が設定されていません"
  exit 1
fi

# name|EDINETコード|プレスリリースURL
companies=(
  "トヨタ自動車|E02144|https://global.toyota/pages/global_toyota/ir/financial-results/2026_4q_presentation_2_jp.pdf"
  "野村総合研究所|E05062|https://ir.nri.com/jp/ir/individual/main/05/teaserItems2/02/linkList/00/link/20250930_pre.pdf"
  "任天堂|E02367|https://www.nintendo.co.jp/ir/pdf/2026/260508_4.pdf"
  "本田技研工業|E02166|https://global.honda/jp/investors/library/financialresult/main/00/teaserItems1/01117/linkList/01/link/FYE202603_4Q_financial_presentation_j_1.pdf"
)

rm -f rows_*.csv

i=0
for entry in "${companies[@]}"; do
  IFS='|' read -r name code url <<< "$entry"
  i=$((i + 1))
  echo "=== [$i/${#companies[@]}] $name ($code) ==="
  python collect.py --edinet "$code" --press-url "$url"
  cp jobs.csv "rows_${i}.csv"
  sleep 2
done

head -n 1 "rows_1.csv" > jobs.csv
for f in rows_*.csv; do
  tail -n +2 "$f" >> jobs.csv
done
rm -f rows_*.csv

echo "[OK] ${#companies[@]}社分を jobs.csv にまとめました"
python engine.py
