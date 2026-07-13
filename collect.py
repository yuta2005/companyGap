"""
collect.py  ─  Day 1-2
求人票を jobs.csv に保存する。

使い方:
  python collect.py            # サンプルデータで即実行（ネット不要）
  python collect.py --scrape   # 求人ボックスから取得を試みる（失敗時はサンプルにフォールバック）
"""

import csv
import time
import sys
import json

OUTPUT = "jobs.csv"
FIELDS = ["title", "company", "desc", "url"]


# ─── サンプルデータ（スクレイピング失敗時 / --scrapeなし時に使用） ────────────
SAMPLE_JOBS = [
    {
        "title": "バックエンドエンジニア（Python/FastAPI）",
        "company": "株式会社テックフォワード",
        "desc": "Pythonを使ったAPIサーバーの設計・開発をお任せします。FastAPI, SQLAlchemy, PostgreSQL を用いたマイクロサービス開発経験者歓迎。AWSでのインフラ運用経験があれば尚可。",
        "url": "https://example.com/job/1",
    },
    {
        "title": "フロントエンドエンジニア（React/TypeScript）",
        "company": "株式会社クリエイトラボ",
        "desc": "ReactとTypeScriptで大規模SPAを開発します。Next.jsの実務経験歓迎。UI/UXデザイナーと密に連携し、ユーザー体験を追求できる方を求めています。",
        "url": "https://example.com/job/2",
    },
    {
        "title": "機械学習エンジニア",
        "company": "AIスタートアップ株式会社",
        "desc": "PythonとPyTorchを使った推薦システム・自然言語処理モデルの研究開発。scikit-learn, pandas, TF-IDFなどの実装経験者優遇。MLflowを使ったモデル管理も担当。",
        "url": "https://example.com/job/3",
    },
    {
        "title": "データサイエンティスト",
        "company": "データドリブン合同会社",
        "desc": "売上予測・顧客分析などの統計モデル構築を担当。Python(pandas, numpy, scikit-learn)必須。SQL, BigQueryを使ったデータ抽出・集計も行います。",
        "url": "https://example.com/job/4",
    },
    {
        "title": "インフラエンジニア（AWS/Terraform）",
        "company": "クラウドソリューションズ株式会社",
        "desc": "AWSを使ったクラウドインフラの構築・運用保守。TerraformによるIaCの導入推進。DockerとKubernetesの知識があれば歓迎。",
        "url": "https://example.com/job/5",
    },
    {
        "title": "フルスタックエンジニア（Django/Vue.js）",
        "company": "ウェブイノベーション株式会社",
        "desc": "DjangoバックエンドとVue.jsフロントエンドを組み合わせたWebアプリ開発。PostgreSQL, Redisも使用。GitHubでのチーム開発に慣れている方。",
        "url": "https://example.com/job/6",
    },
    {
        "title": "Pythonエンジニア（自動化・スクレイピング）",
        "company": "株式会社オートメーション",
        "desc": "Pythonを使った業務自動化ツールの開発。BeautifulSoup, Seleniumでのスクレイピング経験者歓迎。定期実行バッチ処理やAPIとの連携も担当します。",
        "url": "https://example.com/job/7",
    },
    {
        "title": "Webアプリエンジニア（Rails/React）",
        "company": "サービス開発株式会社",
        "desc": "Ruby on RailsのバックエンドAPIとReactフロントエンドの開発。AWSでのデプロイ経験があれば優遇。チームリードの経験がある方も歓迎。",
        "url": "https://example.com/job/8",
    },
    {
        "title": "セキュリティエンジニア",
        "company": "サイバーセキュリティ株式会社",
        "desc": "Webアプリケーションの脆弱性診断・ペネトレーションテスト。Python, Burp Suiteを使った診断業務。セキュリティ資格（情報処理安全確保支援士等）歓迎。",
        "url": "https://example.com/job/9",
    },
    {
        "title": "iOSアプリエンジニア（Swift）",
        "company": "モバイルテック株式会社",
        "desc": "SwiftとXcodeを使ったiOSアプリ開発。UIKitまたはSwiftUIの実務経験必須。REST APIとの連携、App Store申請経験歓迎。",
        "url": "https://example.com/job/10",
    },
    {
        "title": "Androidエンジニア（Kotlin）",
        "company": "株式会社アプリワークス",
        "desc": "KotlinでAndroidネイティブアプリを開発します。Jetpack Compose経験者優遇。Firebase, Google Play Consoleの操作に慣れている方。",
        "url": "https://example.com/job/11",
    },
    {
        "title": "クラウドアーキテクト（GCP）",
        "company": "グローバルITソリューションズ",
        "desc": "Google Cloud Platformでのシステム設計・構築。BigQuery, Cloud Run, PubSubの活用経験歓迎。Pythonでのデータパイプライン構築も担当。",
        "url": "https://example.com/job/12",
    },
    {
        "title": "SREエンジニア",
        "company": "信頼性エンジニアリング株式会社",
        "desc": "サービスの信頼性・可用性向上のためのSRE活動。Prometheus, Grafanaを使った監視基盤の構築。PythonやGoでの自動化スクリプト作成。",
        "url": "https://example.com/job/13",
    },
    {
        "title": "自然言語処理エンジニア（NLP）",
        "company": "言語AIラボ株式会社",
        "desc": "日本語NLPモデルの開発・改善。HuggingFace Transformers, BERTの fine-tuning 経験歓迎。PythonとPyTorchが必須。大規模テキストデータの処理・分析も担当。",
        "url": "https://example.com/job/14",
    },
    {
        "title": "データエンジニア（Spark/Airflow）",
        "company": "データプラットフォーム株式会社",
        "desc": "Apache SparkとAirflowを使ったデータパイプライン構築。Python, SQLが必須。AWSまたはGCPのマネージドサービスの利用経験者歓迎。",
        "url": "https://example.com/job/15",
    },
    {
        "title": "ゲームバックエンドエンジニア",
        "company": "ゲームスタジオ株式会社",
        "desc": "オンラインゲームのサーバーサイド開発。Go言語またはPythonを使ったAPI開発。Redisを使ったセッション管理、MySQLでのデータ設計も担当。",
        "url": "https://example.com/job/16",
    },
    {
        "title": "ブロックチェーンエンジニア（Solidity）",
        "company": "Web3スタートアップ",
        "desc": "EthereumのスマートコントラクトをSolidityで開発。HardhatやFoundryを使ったテスト環境の構築経験者歓迎。JavaScriptまたはPythonでのDApps開発も担当。",
        "url": "https://example.com/job/17",
    },
    {
        "title": "組み込みエンジニア（C/C++）",
        "company": "デバイス製造株式会社",
        "desc": "マイコン向けファームウェア開発。C/C++必須、RTO Sの知識があれば歓迎。Pythonを使ったテスト自動化スクリプトの作成も行います。",
        "url": "https://example.com/job/18",
    },
    {
        "title": "QAエンジニア（自動化テスト）",
        "company": "品質保証テック株式会社",
        "desc": "PythonとSeleniumを使ったE2Eテスト自動化。Pytest, GitHub Actionsでの CI/CD パイプライン構築。Webアプリの品質保証全般を担当します。",
        "url": "https://example.com/job/19",
    },
    {
        "title": "Webデザイナー兼フロントエンジニア",
        "company": "デザインテック株式会社",
        "desc": "FigmaでUIデザインし、HTML/CSS/JavaScriptで実装まで行います。Reactの基礎知識歓迎。アクセシビリティ・パフォーマンスを意識した実装ができる方。",
        "url": "https://example.com/job/20",
    },
]


# ─── スクレイピング（求人ボックス） ───────────────────────────────────────────
def scrape_kyujin_box(keyword="エンジニア", pages=3):
    """求人ボックスから求人を取得する（失敗したら空リストを返す）"""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("[WARN] requests / beautifulsoup4 未インストール。サンプルデータを使います。")
        print("       pip install requests beautifulsoup4")
        return []

    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for page in range(1, pages + 1):
        url = f"https://xn--pckua2a7gp15o89zb.jp/?q={keyword}&p={page}"
        print(f"  取得中: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")

            # 求人ボックスの求人カード（クラス名は変更される場合あり）
            cards = soup.select("article.result-box") or soup.select(".job-card") or soup.select("[class*='result']")
            if not cards:
                print(f"  [WARN] ページ {page}: カードが見つかりません（HTML構造が変わった可能性）")
                continue

            for card in cards:
                title_el   = card.select_one("h2, .job-title, [class*='title']")
                company_el = card.select_one("[class*='company'], [class*='employer']")
                desc_el    = card.select_one("[class*='desc'], [class*='detail'], p")
                link_el    = card.select_one("a[href]")

                jobs.append({
                    "title":   title_el.text.strip()   if title_el   else "（タイトルなし）",
                    "company": company_el.text.strip() if company_el else "（会社名なし）",
                    "desc":    desc_el.text.strip()    if desc_el    else "",
                    "url":     link_el["href"]         if link_el    else "",
                })

            time.sleep(1)  # サーバー負荷軽減
        except Exception as e:
            print(f"  [ERROR] ページ {page} 取得失敗: {e}")
            continue

    return jobs


# ─── メイン ──────────────────────────────────────────────────────────────────
def save_csv(jobs, path=OUTPUT):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"[OK] {len(jobs)} 件を {path} に保存しました")


def main():
    use_scrape = "--scrape" in sys.argv

    if use_scrape:
        print("[INFO] 求人ボックスからスクレイピング中...")
        keyword = sys.argv[sys.argv.index("--scrape") + 1] if "--scrape" in sys.argv and sys.argv.index("--scrape") + 1 < len(sys.argv) else "エンジニア"
        jobs = scrape_kyujin_box(keyword)
        if not jobs:
            print("[WARN] スクレイピング失敗 -> サンプルデータで代替します")
            jobs = SAMPLE_JOBS
    else:
        print("[INFO] サンプルデータ（20件）を使用します")
        print("       実際の求人を使う場合: python collect.py --scrape エンジニア")
        jobs = SAMPLE_JOBS

    save_csv(jobs)


if __name__ == "__main__":
    main()
