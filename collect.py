# -*- coding: utf-8 -*-
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
  3. python collect.py                       # サンプルデータ(5社)を保存
     python collect.py --edinet E02144       # 実データ取得(トヨタの例、IR資料のみ)
     python collect.py --edinet E02144 --press-url https://example.com/press.pdf
                                              # プレスリリースPDF/HTMLも合わせて取得
     python collect.py --batch companies.csv # 企業リストからまとめて実データ取得
                                              # (列: company,edinet_code,press_url)
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


def _redact(text: str) -> str:
    """例外メッセージからAPIキーを除去する(Subscription-Keyはクエリパラメータで
    送信されるため、requestsの例外にはURL全体＝キー入りの文字列が含まれる)。"""
    if API_KEY and API_KEY in text:
        return text.replace(API_KEY, "***")
    return text


# ══════════════════════════════════════════════════════════════════════
# 1. EDINET: 書類一覧の取得
# ══════════════════════════════════════════════════════════════════════


# 日付ごとの書類一覧キャッシュ。バッチ収集時に同じ日付を
# 企業ごとに再取得しないようにする(API負荷とレート制限対策)。
_DOC_LIST_CACHE: dict[str, list] = {}


def fetch_document_list(date: str) -> list[dict]:
    """指定日に提出された書類一覧を取得(メタデータのみ・日付単位でキャッシュ)"""
    if date in _DOC_LIST_CACHE:
        return _DOC_LIST_CACHE[date]
    if not API_KEY:
        print("[ERROR] 環境変数 EDINET_API_KEY が設定されていません")
        return []
    url = f"{EDINET_BASE}/documents.json"
    params = {"date": date, "type": 2, "Subscription-Key": API_KEY}
    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        data = res.json()
        results = data.get("results", [])
        _DOC_LIST_CACHE[date] = results
        time.sleep(0.3)  # 実リクエスト時のみAPI負荷軽減
        return results
    except Exception as e:
        print(f"  [ERROR] 書類一覧取得失敗 ({date}): {_redact(str(e))}")
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

    if not API_KEY:
        print("[ERROR] 環境変数 EDINET_API_KEY が設定されていません")
        return None

    today = _date.today()
    for i in range(days_back):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        doc = find_yuho(edinet_code, d)
        if doc:
            return doc
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
        print(f"  [ERROR] 書類本文取得失敗 ({doc_id}): {_redact(str(e))}")
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
            print(
                f"  [WARN] 未対応の形式のためスキップ ({content_type or '不明'}): {url}"
            )
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
    company_name = doc.get("filerName") or company
    ir_text = download_yuho_text(doc["docID"])
    if not ir_text:
        print(f"  [{company_name}] 本文抽出に失敗しました")
        return None
    press_text = fetch_press_release(press_url) if press_url else ""
    return {
        "company": company_name,
        "ir_summary": ir_text,
        "press_release": press_text,
    }


def collect_batch(list_path: str) -> list[dict]:
    """企業リストCSV(列: company,edinet_code,press_url)からまとめて実データを収集。
    書類一覧は日付単位でキャッシュされるため、2社目以降の有報検索は高速。
    取得に失敗した企業はスキップして続行する。"""
    if not os.path.exists(list_path):
        print(f"[ERROR] 企業リストが見つかりません: {list_path}")
        return []
    rows = []
    with open(list_path, encoding="utf-8-sig") as f:
        companies = [r for r in csv.DictReader(f) if r.get("edinet_code")]
    for i, c in enumerate(companies, 1):
        name = (c.get("company") or "").strip()
        code = c["edinet_code"].strip()
        url = (c.get("press_url") or "").strip()
        print(f"=== [{i}/{len(companies)}] {name} ({code}) ===")
        row = collect_company(name or f"企業({code})", code, url)
        if row:
            rows.append(row)
        else:
            print(f"  [WARN] {name} の取得に失敗したためスキップします")
        time.sleep(1)  # 連続アクセスの間隔
    return rows


# ══════════════════════════════════════════════════════════════════════
# 5. サンプルデータ ─ 5社分
#    ※実データ取得(EDINET API登録)が未完了でも動作確認できるよう用意。
#      内容は「決算の事実」と「プレスリリースの見出し表現」の
#      典型的なズレパターンを想定して作成した合成データ(実在企業の
#      引用ではない)。有報の「経営方針・課題」欄に近い分量・文体とし、
#      IR/プレス間で語彙が部分的に重なるよう設計している(実データでは
#      完全に語彙が分離することはまずないため)。
#      想定する乖離度: A・C・E社(大きい) > B・D社(小さい)
# ══════════════════════════════════════════════════════════════════════

SAMPLE_DATA = [
    {
        # パターン: 業績悪化をバズワードで覆い隠す(乖離: 大)
        "company": "A社(小売)",
        "ir_summary": (
            "当期におけるわが国経済は、雇用環境の改善が続いたものの、"
            "物価上昇を背景とした消費者の節約志向が強まり、小売業界を取り巻く環境は"
            "厳しい状況で推移した。このような環境のもと、当期の売上高は前期比3.2%減の"
            "2,845億円、営業利益は前期比18.7%減の98億円となった。"
            "主要因は既存店売上の低迷に加え、原材料価格および物流費の上昇に伴う"
            "売上原価率の悪化である。特に衣料品部門では天候不順の影響により"
            "季節商品の販売が計画を下回った。"
            "国内市場の縮小が続くなか、来期は不採算店舗の閉鎖を含む店舗網の見直しを"
            "進めるとともに、販売管理費の削減に取り組む。"
            "また、ECサイトの利便性向上をはじめとするデジタル化への対応の遅れを"
            "重要な経営課題として認識している。"
        ),
        "press_release": (
            "新たな成長ステージへ ― 当社は本日、中期経営計画「NEXT VISION」を"
            "発表しました。顧客体験の革新を通じて持続的な価値創造を実現します。"
            "デジタル戦略を加速し、ECと店舗を融合した新しい買物体験を提供してまいります。"
            "次年度は攻めの投資フェーズと位置づけ、成長領域への経営資源のシフトを"
            "大胆に進めます。私たちは、お客様とともに未来の小売業の姿を描いてまいります。"
        ),
    },
    {
        # パターン: 事実をほぼそのまま伝える誠実なリリース(乖離: 小)
        "company": "B社(製造)",
        "ir_summary": (
            "当期の売上高は前期比5.1%増の5,120億円、営業利益は前期比6.3%増の"
            "412億円となった。北米および東南アジア向けの産業機械の販売が堅調に"
            "推移したことが主な要因である。為替の円安基調も輸出採算の改善に寄与した。"
            "生産面では、国内主力工場の設備投資が計画通り進捗しており、"
            "来期も生産能力の増強を継続する。"
            "一方、原材料価格の高止まりや部品調達の遅延リスクが引き続き課題であり、"
            "調達先の分散とコスト低減活動を進めている。"
            "海外売上高比率は58%となり、グローバルな事業展開が着実に進んでいる。"
        ),
        "press_release": (
            "増収増益を達成 ― 当期の売上高は前期比5.1%増の5,120億円、営業利益は"
            "同6.3%増の412億円となりました。北米・東南アジア向け産業機械の販売が"
            "堅調に推移し、海外売上高比率は58%に達しました。"
            "国内主力工場では計画通り設備投資を進めており、来期も生産能力の増強を"
            "継続します。原材料価格の高止まりに対しては、調達先の分散などにより"
            "対応してまいります。"
        ),
    },
    {
        # パターン: 大幅減益・減損を「挑戦」「転換」の物語にすり替える(乖離: 中〜大)
        "company": "C社(IT)",
        "ir_summary": (
            "当期の売上高は前期比8.4%減の680億円、営業利益は前期比42.0%減の"
            "31億円となった。主力の受託開発事業において大口顧客からの受注が"
            "減少したことに加え、エンジニアの採用強化に伴う人件費の増加が利益を"
            "圧迫した。また、一部子会社ののれんについて減損損失23億円を計上した。"
            "受託開発への依存度の高さが収益変動リスクとなっており、自社プロダクトに"
            "よる継続収益(ストック型収益)の拡大が経営上の最重要課題である。"
            "来期は不採算プロジェクトの整理を進めるとともに、開発体制の効率化を図る。"
        ),
        "press_release": (
            "新規事業領域への挑戦を加速 ― 当社は、AIを活用した次世代SaaS"
            "プロダクトの開発に注力し、ストック型収益モデルへの転換を進めています。"
            "エンジニア採用も積極的に強化しており、開発組織は過去最大規模と"
            "なりました。中長期的な企業価値向上を目指す新たなフェーズに入り、"
            "変革のスピードをさらに上げてまいります。"
        ),
    },
    {
        # パターン: 好業績を事実ベースで伝える(乖離: 最小)。免責定型文入り
        "company": "D社(食品)",
        "ir_summary": (
            "当期の売上高は前期比7.8%増の3,420億円、営業利益は前期比12.5%増の"
            "356億円となり、売上高・営業利益ともに過去最高を更新した。"
            "主力ブランドの調味料および飲料の販売が国内外で好調に推移したことに"
            "加え、前年に実施した価格改定の浸透が寄与した。"
            "海外では東南アジア市場での販売網の拡大が進み、海外売上高は前期比"
            "15%増となった。一方、原材料価格の変動や為替リスクへの対応、"
            "国内人口減少に伴う市場縮小への備えが中長期的な課題である。"
            "健康志向の高まりに対応した新商品の開発を継続する。"
        ),
        "press_release": (
            "過去最高益を更新 ― 当期の売上高は3,420億円、営業利益は356億円となり、"
            "ともに過去最高を更新しました。主力ブランドの調味料・飲料が国内外で"
            "好調に推移し、東南アジアでの販売網の拡大も寄与しています。"
            "健康志向に対応した新商品の投入を継続し、お客様への価値提供を"
            "さらに進めてまいります。"
            "なお、本資料は投資判断の参考となる情報の提供を目的としたものであり、"
            "投資勧誘を目的としたものではありません。"
        ),
    },
    {
        # パターン: 損失処理を「最適化」と言い換える(乖離: 中)
        "company": "E社(不動産)",
        "ir_summary": (
            "当期の売上高は前期比1.2%増の1,980億円、営業利益は前期比横ばいの"
            "210億円となった。オフィスビル賃貸事業は空室率の上昇により賃料収入が"
            "伸び悩んだ。また、保有物件のうち収益性の低下した地方商業施設について、"
            "含み損を一部実現し特別損失45億円を計上した。"
            "金利上昇局面において資金調達コストの増加が見込まれ、市況の先行き"
            "不透明感が続く。有利子負債の圧縮と保有資産の入替えを進め、"
            "財務基盤の安定化を図ることが課題である。"
        ),
        "press_release": (
            "資産ポートフォリオの最適化を断行 ― 当社は、将来の収益基盤の強化に"
            "向けた戦略的な資産の入替えを実施しました。厳選した優良物件への投資に"
            "より、ポートフォリオの質は着実に向上しています。"
            "財務基盤の強化と成長投資の両立を図り、企業価値の向上を目指して"
            "まいります。"
        ),
    },
]


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
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        list_path = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "companies.csv"
        rows = collect_batch(list_path)
        if rows:
            save_csv(rows)
        else:
            print("[WARN] 1社も取得できませんでした。サンプルデータを保存します。")
            save_csv(SAMPLE_DATA)
        return

    if "--edinet" in sys.argv:
        idx = sys.argv.index("--edinet")
        args = sys.argv[idx + 1 :]
        if len(args) < 1:
            print(
                "[ERROR] 使い方: python collect.py --edinet <EDINETコード> [--press-url <URL>]"
            )
            sys.exit(1)
        edinet_code = args[0]
        press_url = ""
        if "--press-url" in args:
            p_idx = args.index("--press-url")
            if len(args) > p_idx + 1:
                press_url = args[p_idx + 1]
        row = collect_company(f"企業({edinet_code})", edinet_code, press_url)
        if row:
            save_csv([row])
        else:
            print("[WARN] 取得できませんでした。サンプルデータを保存します。")
            save_csv(SAMPLE_DATA)
    else:
        print("[INFO] サンプルデータ(合成・5社分)を保存します")
        print("       実データ取得: EDINET_API_KEY を設定の上")
        print("       python collect.py --edinet <EDINETコード>")
        save_csv(SAMPLE_DATA)


if __name__ == "__main__":
    main()
