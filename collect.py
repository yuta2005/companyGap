"""
collect.py  ─  IR資料(有価証券報告書) と プレスリリースの乖離度測定用データ収集
著作権上の安全性を重視し、体験記サイトのスクレイピングは廃止。
代わりに以下の二種類を比較する:
  - ir_summary      : EDINET(金融庁)から取得した有価証券報告書の
                       「経営方針、経営環境及び対処すべき課題等」等の事実ベース記述
  - press_release   : 企業公式IRページのプレスリリース／決算サマリー(見出し・アピール文)

EDINET は著作権法30条の4(情報解析目的の利用)の趣旨に合致し、
かつ金融庁が公的に開示している一次情報のため、体験記サイトよりも
著作権・利用規約上のリスクが低い。

使い方:
  1. EDINET利用者登録 → APIキー発行
     https://disclosure2.edinet-fsa.go.jp/  (マイページ > API利用者登録)
  2. 環境変数にキーを設定
     export EDINET_API_KEY="発行されたキー"
  3. python collect.py                       # サンプルデータ(20社)を保存
     python collect.py --edinet E02144 2024-06-25   # 実データ取得(トヨタの例)
"""

import os
import re
import sys
import csv
import time
import json
import io
import zipfile
import requests

OUTPUT = "jobs.csv"
FIELDS = ["company", "ir_summary", "press_release"]

EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
API_KEY = os.environ.get("EDINET_API_KEY", "")

UA = "Mozilla/5.0 (research-bot; university-assignment; mailto:your@email.com)"


# ══════════════════════════════════════════════════════════════════════
# 1. EDINET: 書類一覧の取得
# ══════════════════════════════════════════════════════════════════════


def fetch_document_list(date: str) -> list[dict]:
    """指定日に提出された書類一覧を取得(メタデータのみ)"""
    if not API_KEY:
        print("[ERROR] 環境変数 EDINET_API_KEY が設定されていません")
        return []
    url = f"{EDINET_BASE}/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": API_KEY}
    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        data = res.json()
        return data.get("results", [])
    except Exception as e:
        print(f"  [ERROR] 書類一覧取得失敗 ({date}): {e}")
        return []


def find_yuho(edinet_code: str, date: str) -> dict | None:
    """指定日の書類一覧から、指定企業(edinetCode)の有価証券報告書(docTypeCode=120)を探す"""
    docs = fetch_document_list(date)
    for d in docs:
        if d.get("edinetCode") == edinet_code and d.get("docTypeCode") == "120":
            return d
    return None


def search_yuho_recent(edinet_code: str, days_back: int = 400) -> dict | None:
    """過去 days_back 日をさかのぼって有価証券報告書を探す(年1回提出のため広めに探索)"""
    from datetime import date as _date, timedelta

    today = _date.today()
    for i in range(days_back):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        doc = find_yuho(edinet_code, d)
        if doc:
            return doc
        time.sleep(0.3)  # API負荷軽減
    return None


# ══════════════════════════════════════════════════════════════════════
# 2. EDINET: 書類本文(CSV形式)のダウンロードとテキスト抽出
# ══════════════════════════════════════════════════════════════════════

# 抽出したい非財務テキスト項目(XBRL要素名の一部)
TARGET_ELEMENTS = [
    "jpcrp_cor:BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock",  # 経営方針・経営環境・対処すべき課題
    "jpcrp_cor:DescriptionOfBusinessTextBlock",  # 事業の内容
]


def download_yuho_text(doc_id: str) -> str:
    """
    有価証券報告書をCSV形式(type=5)で取得し、
    「経営方針、経営環境及び対処すべき課題等」等のテキストを抽出する。
    """
    if not API_KEY:
        return ""
    url = f"{EDINET_BASE}/documents/{doc_id}"
    params = {"type": 5, "Subscription-Key": API_KEY}
    try:
        res = requests.get(url, params=params, timeout=30)
        res.raise_for_status()
        texts = []
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            for name in z.namelist():
                if not (name.startswith("XBRL_TO_CSV/jpcrp") and name.endswith(".csv")):
                    continue
                with z.open(name) as f:
                    # EDINETのCSVはUTF-16タブ区切り
                    content = f.read().decode("utf-16")
                    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
                    for row in reader:
                        elem = row.get("要素ID", "")
                        if any(t in elem for t in TARGET_ELEMENTS):
                            val = row.get("値", "")
                            if val:
                                texts.append(val)
        raw = " ".join(texts)
        # HTMLタグ除去(XBRLテキストブロックにHTMLが含まれることがある)
        clean = re.sub(r"<[^>]+>", " ", raw)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:2000]
    except Exception as e:
        print(f"  [ERROR] 書類本文取得失敗 ({doc_id}): {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════
# 3. プレスリリース取得(企業公式IRページ, robots.txt確認付き)
# ══════════════════════════════════════════════════════════════════════


def can_fetch(url: str) -> bool:
    from urllib.parse import urlparse
    from urllib.robotparser import RobotFileParser

    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        res = requests.get(robots_url, headers={"User-Agent": UA}, timeout=5)
        rp.parse(res.text.splitlines())
        allowed = rp.can_fetch(UA, url)
        if not allowed:
            print(f"  [robots.txt] NG: {url}")
        return allowed
    except Exception as e:
        print(f"  [robots.txt] 確認失敗 ({e}) → スキップ")
        return False


def fetch_press_release(url: str) -> str:
    """企業公式IRページ／プレスリリースページのテキストを取得(robots.txt確認済み)。
    決算説明資料等はPDF公開が主流のため、PDF・HTMLの両方に対応する。"""
    try:
        if not can_fetch(url):
            return ""
        res = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        content_type = res.headers.get("Content-Type", "").lower()
        time.sleep(1.5)

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(res.content))
            text = " ".join(page.extract_text() or "" for page in reader.pages)
        elif "html" in content_type:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(res.content, "html.parser")
            main = soup.find("main") or soup.find("article") or soup.body
            text = main.get_text(separator=" ", strip=True) if main else ""
        else:
            print(f"  [WARN] 未対応の形式のためスキップ ({content_type or '不明'}): {url}")
            return ""

        return re.sub(r"\s+", " ", text)[:1000]
    except Exception as e:
        print(f"  [ERROR] プレスリリース取得失敗 ({url}): {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════
# 4. 実データ収集のメインフロー
# ══════════════════════════════════════════════════════════════════════


def collect_company(company: str, edinet_code: str, press_url: str = "") -> dict | None:
    print(f"  [{company}] EDINETから有価証券報告書を検索中...")
    doc = search_yuho_recent(edinet_code)
    if not doc:
        print(f"  [{company}] 有価証券報告書が見つかりませんでした")
        return None
    ir_text = download_yuho_text(doc["docID"])
    if not ir_text:
        print(f"  [{company}] 本文抽出に失敗しました")
        return None
    press_text = fetch_press_release(press_url) if press_url else ""
    return {
        "company": company,
        "ir_summary": ir_text,
        "press_release": press_text,
    }


# ══════════════════════════════════════════════════════════════════════
# 5. サンプルデータ(合成) ─ 20社分
#    ※実データ取得(EDINET API登録)が未完了でも動作確認できるよう用意。
#      内容は「決算の事実」と「プレスリリースの見出し表現」の
#      典型的なズレパターンを想定して作成した合成データ(実在企業の
#      引用ではない)。
# ══════════════════════════════════════════════════════════════════════

SAMPLE_DATA = [
    {
        "company": "A社(小売)",
        "ir_summary": (
            "当期の売上高は前期比3.2%減少し、営業利益は前期比18.7%の減益となった。"
            "主要因は既存店売上の低迷と、原材料価格上昇に伴う売上原価率の悪化である。"
            "国内市場の縮小を受け、来期は店舗数の見直しを検討している。"
        ),
        "press_release": (
            "新たな成長ステージへ。当社は顧客体験の革新を通じて持続的な価値創造を実現します。"
            "デジタル戦略の加速により、次年度は攻めの投資フェーズに入ります。"
        ),
    },
    {
        "company": "B社(製造)",
        "ir_summary": (
            "当期の売上高は前期比5.1%増加し、営業利益は前期比6.3%増加した。"
            "海外向け販売が堅調に推移したことが主な要因である。"
            "設備投資は計画通り進捗しており、生産能力の増強を継続する。"
        ),
        "press_release": (
            "グローバル展開が着実に進展。海外売上の伸長を背景に増収増益を達成しました。"
            "今後も持続的な成長を目指します。"
        ),
    },
    {
        "company": "C社(IT)",
        "ir_summary": (
            "当期の営業利益は前期比42%減少した。主力事業の受注減少および人件費増加が影響した。"
            "一部子会社において減損損失を計上している。"
        ),
        "press_release": (
            "新規事業領域への挑戦を加速。次世代プロダクトの開発に注力し、"
            "中長期的な企業価値向上を目指すフェーズに入りました。"
        ),
    },
    {
        "company": "D社(食品)",
        "ir_summary": (
            "当期の売上高、営業利益ともに前期を上回り、過去最高益を更新した。"
            "主力ブランドの販売が国内外で好調に推移した。"
        ),
        "press_release": (
            "過去最高益を達成。お客様への価値提供が着実に成果として実を結んでいます。"
        ),
    },
    {
        "company": "E社(不動産)",
        "ir_summary": (
            "当期は保有物件の含み損を一部実現し、特別損失を計上した。"
            "営業利益は前期比横ばいで推移している。市況の先行き不透明感が続く。"
        ),
        "press_release": (
            "資産ポートフォリオの最適化を断行。将来の収益基盤強化に向けた"
            "戦略的な一手として評価しています。"
        ),
    },
]

# 残り15社分は上記5パターンをベースにした簡易バリエーション
_EXTRA_NAMES = [
    "F社(通信)",
    "G社(化学)",
    "H社(運輸)",
    "I社(金融)",
    "J社(医薬)",
    "K社(電機)",
    "L社(サービス)",
    "M社(建設)",
    "N社(エネルギー)",
    "O社(商社)",
    "P社(自動車)",
    "Q社(繊維)",
    "R社(鉄鋼)",
    "S社(海運)",
    "T社(教育)",
]
for i, name in enumerate(_EXTRA_NAMES):
    base = SAMPLE_DATA[i % 5]
    SAMPLE_DATA.append(
        {
            "company": name,
            "ir_summary": base["ir_summary"],
            "press_release": base["press_release"],
        }
    )


# ══════════════════════════════════════════════════════════════════════
# 6. CSV保存 & メイン
# ══════════════════════════════════════════════════════════════════════


def save_csv(data: list, path: str = OUTPUT) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
    print(f"[OK] {len(data)} 件を {path} に保存しました")


def main():
    if "--edinet" in sys.argv:
        idx = sys.argv.index("--edinet")
        args = sys.argv[idx + 1 :]
        if len(args) < 1:
            print(
                "[ERROR] 使い方: python collect.py --edinet <EDINETコード> [基準日 YYYY-MM-DD]"
            )
            sys.exit(1)
        edinet_code = args[0]
        row = collect_company(f"企業({edinet_code})", edinet_code)
        if row:
            save_csv([row])
        else:
            print("[WARN] 取得できませんでした。サンプルデータを保存します。")
            save_csv(SAMPLE_DATA)
    else:
        print("[INFO] サンプルデータ(合成・20社分)を保存します")
        print("       実データ取得: EDINET_API_KEY を設定の上")
        print("       python collect.py --edinet <EDINETコード>")
        save_csv(SAMPLE_DATA)


if __name__ == "__main__":
    main()
