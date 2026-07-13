"""
collect.py  ─  企業採用ページ & インターン体験記を収集して jobs.csv に保存

使い方:
  python collect.py                    # サンプルデータ（20社）を保存
  python collect.py --scrape トヨタ    # 実際にスクレイピングを試みる（失敗時はサンプル）
"""

import csv
import sys
import time
import json
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

OUTPUT = "jobs.csv"
FIELDS = ["company", "company_page", "intern_report"]

UA = "Mozilla/5.0 (research-bot; mailto:your@email.com)"

# ─── robots.txt チェック ───────────────────────────────────────────────────────
def can_fetch(url: str) -> bool:
    """robots.txt を確認して取得可否を返す"""
    try:
        import requests
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        res = requests.get(robots_url, headers={"User-Agent": UA}, timeout=5)
        rp.parse(res.text.splitlines())
        allowed = rp.can_fetch(UA, url)
        if not allowed:
            print(f"  [robots.txt] NG: {url}")
        return allowed
    except Exception as e:
        print(f"  [robots.txt] 確認失敗 ({e}) → スキップ")
        return False


# ─── スクレイピング関数 ────────────────────────────────────────────────────────
def scrape_one_career(company: str) -> list[str]:
    """ワンキャリアのインターン体験記を取得（robots.txt 確認済み）"""
    try:
        import requests
        from bs4 import BeautifulSoup
        base = "https://one-career.jp"
        url  = f"{base}/search?q={company}&type=intern_experience"
        if not can_fetch(url):
            return []
        res  = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        reviews = [el.text.strip() for el in soup.select(".review-body, .experience-text, article p")]
        time.sleep(1.5)
        return [r for r in reviews if len(r) > 30][:5]
    except Exception as e:
        print(f"  [ERROR] ワンキャリア取得失敗: {e}")
        return []


def scrape_shukatsu_kaigi(company: str) -> list[str]:
    """就活会議のインターン体験記を取得（robots.txt 確認済み）"""
    try:
        import requests
        from bs4 import BeautifulSoup
        base = "https://syukatsu-kaigi.jp"
        url  = f"{base}/companies/search?q={company}"
        if not can_fetch(url):
            return []
        res  = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        reviews = [el.text.strip() for el in soup.select(".review-content, .intern-review, .body-text")]
        time.sleep(1.5)
        return [r for r in reviews if len(r) > 30][:5]
    except Exception as e:
        print(f"  [ERROR] 就活会議取得失敗: {e}")
        return []


def scrape_company_page(url: str) -> str:
    """企業採用ページのテキストを取得（robots.txt 確認済み）"""
    try:
        import requests
        from bs4 import BeautifulSoup
        if not can_fetch(url):
            return ""
        res  = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        # <main> または <article> のテキストを優先
        main = soup.find("main") or soup.find("article") or soup.body
        text = main.get_text(separator=" ", strip=True) if main else ""
        time.sleep(1.5)
        return re.sub(r"\s+", " ", text)[:1000]
    except Exception as e:
        print(f"  [ERROR] 採用ページ取得失敗 ({url}): {e}")
        return ""


def scrape_company(company: str) -> dict | None:
    """1社分のデータを収集して dict を返す"""
    print(f"  [{company}] 収集中...")
    reviews = scrape_one_career(company) or scrape_shukatsu_kaigi(company)
    if not reviews:
        print(f"  [{company}] 体験記が取得できませんでした")
        return None
    return {
        "company":       company,
        "company_page":  "",        # 採用ページURLが判明したら scrape_company_page() を使う
        "intern_report": " ".join(reviews),
    }


# ─── サンプルデータ ────────────────────────────────────────────────────────────
SAMPLE_DATA = [
    {
        "company": "株式会社グロースビジョン",
        "company_page": (
            "風通しの良いフラットな組織で、若手でも裁量を持って挑戦できる環境です。"
            "メンバー全員が意見を言い合えるオープンな文化を大切にしています。"
            "インターンにもプロジェクトのオーナーシップを与え、成長を全力でサポートします。"
        ),
        "intern_report": (
            "実際には上司の指示を待つだけで、自分から提案しても却下されることがほとんどでした。"
            "会議はほぼ報告の場で、若手が発言できる雰囲気ではありませんでした。"
            "裁量はほとんどなく、毎日同じ作業の繰り返しでした。"
        ),
    },
    {
        "company": "テックイノベーション合同会社",
        "company_page": (
            "最新技術を積極的に導入し、エンジニアが技術的挑戦に集中できる環境を整備しています。"
            "週1回の勉強会や技術共有の場を設け、チーム全体でスキルアップを目指しています。"
            "コードレビューを丁寧に行い、成長をサポートします。"
        ),
        "intern_report": (
            "使用している技術スタックは古く、レガシーコードの保守が中心でした。"
            "勉強会は存在しましたが、参加は任意で実質業務後の残業扱いでした。"
            "コードレビューは丁寧で、メンターの方も親切に教えてくれました。"
        ),
    },
    {
        "company": "フューチャーデザイン株式会社",
        "company_page": (
            "ワークライフバランスを重視し、残業ゼロを目指しています。"
            "リモートワーク推進で、場所を選ばず柔軟に働けます。"
            "社員の健康を第一に考えた働き方改革を積極的に推進中です。"
        ),
        "intern_report": (
            "インターン期間中も残業は当たり前で、平均毎日2〜3時間は残っていました。"
            "リモートは週1回のみで、実態はほぼフル出社でした。"
            "ワークライフバランスという言葉がむしろ違和感でした。"
        ),
    },
    {
        "company": "サステナブルテック株式会社",
        "company_page": (
            "社会課題の解決に向けた事業を展開し、社員一人ひとりが社会貢献を実感できる環境です。"
            "SDGsへの取り組みを全社で推進し、持続可能な未来の実現に貢献しています。"
            "インターンも実際のプロジェクトに参加し、社会的インパクトを体験できます。"
        ),
        "intern_report": (
            "実際にSDGsに関連するプロジェクトに参画でき、やりがいを感じました。"
            "社会貢献への意識が高い社員が多く、日々の業務でその姿勢を学べました。"
            "インターンでも実際の顧客とのミーティングに同席でき、貴重な体験ができました。"
        ),
    },
    {
        "company": "クリエイティブラボ株式会社",
        "company_page": (
            "クリエイターが自由に発想を広げられる創造的な職場環境を提供しています。"
            "デザインと技術の融合を追求し、革新的なプロダクトを生み出しています。"
            "インターンにもオリジナルの制作物を発表する機会があります。"
        ),
        "intern_report": (
            "デザインの裁量は上位メンバーに集中しており、インターンは素材作成が中心でした。"
            "発表の機会はありましたが、発表後のフィードバックが薄く改善につながりにくかったです。"
            "職場の雰囲気は自由ですが、アウトプットへの評価基準が不明確でした。"
        ),
    },
    {
        "company": "グローバルコネクト株式会社",
        "company_page": (
            "グローバルに活躍するチームで、英語を使った業務が日常的です。"
            "海外拠点とのコラボレーションが多く、国際的なキャリアを築けます。"
            "多様なバックグラウンドを持つメンバーと共に働く、真のダイバーシティ環境です。"
        ),
        "intern_report": (
            "英語を使う機会は週に1〜2回の国際ミーティングのみで、日常業務は日本語中心でした。"
            "海外拠点との連携はありましたが、インターンが参加できる機会は限られていました。"
            "チームの多様性は感じましたが、実際のグローバル業務への関与は少なかったです。"
        ),
    },
    {
        "company": "アカデミックブリッジ株式会社",
        "company_page": (
            "研究と実務を結ぶブリッジとして、学術的知見を社会実装するミッションを持っています。"
            "大学・研究機関との連携が強く、最先端の知識を実ビジネスに活かせます。"
            "インターンも論文執筆や学会発表のサポートができる環境です。"
        ),
        "intern_report": (
            "実際に大学教授や研究者と連携するプロジェクトに参加でき、刺激的でした。"
            "論文レビューや資料まとめなど、アカデミックな作業が多く学びが深かったです。"
            "学会発表の準備を手伝えたことは、貴重な経験になりました。"
        ),
    },
    {
        "company": "ハイスピードベンチャー株式会社",
        "company_page": (
            "スタートアップのスピード感で意思決定し、挑戦を楽しめる人を歓迎します。"
            "失敗を恐れずチャレンジできる文化があり、高速でのPDCAを回せます。"
            "インターンでも重要な役割を担い、会社の成長に貢献できます。"
        ),
        "intern_report": (
            "スピード感は本当に速く、毎日変化があり刺激的でした。"
            "任された業務の責任範囲が広く、プレッシャーはありましたが成長できました。"
            "失敗してもすぐ次に切り替える文化があり、前向きに取り組めました。"
        ),
    },
    {
        "company": "コンサルパートナーズ株式会社",
        "company_page": (
            "論理的思考力と実行力を兼ね備えたコンサルタントを育てる環境があります。"
            "クライアントの経営課題に向き合い、ビジネスインパクトを創出できます。"
            "インターンも実際のプロジェクトにアサインされ、本物の仕事を経験できます。"
        ),
        "intern_report": (
            "実際のプロジェクトにアサインされましたが、主にデータ集計や資料作成が中心でした。"
            "クライアントとの会議には同席しましたが、発言の機会はありませんでした。"
            "論理的思考のトレーニングは充実しており、フレームワーク学習は役立ちました。"
        ),
    },
    {
        "company": "ウェルネステック株式会社",
        "company_page": (
            "社員の健康と幸福を最優先に、心理的安全性の高い職場環境を構築しています。"
            "1on1ミーティングを毎週実施し、社員一人ひとりのメンタルケアを徹底します。"
            "有給消化率100%を達成し、働きやすさNO.1を目指しています。"
        ),
        "intern_report": (
            "1on1は確かに毎週ありましたが、形式的で相談しにくい雰囲気でした。"
            "インターン期間中は有給がなく、体調不良時の対応が不明確でした。"
            "社員の方々は忙しそうで、心理的安全性とは言いにくい空気を感じました。"
        ),
    },
    {
        "company": "エドテックジャパン株式会社",
        "company_page": (
            "教育×テクノロジーで日本の学習環境を変革する、情熱あるチームです。"
            "全社員が教育への深い信念を持ち、ユーザーファーストを徹底しています。"
            "インターンにも製品改善のアイデアを提案・実装できる機会があります。"
        ),
        "intern_report": (
            "教育への熱量が高い社員が多く、ミッションへの共感が強い環境でした。"
            "ユーザーの声を直接聞くインタビューに参加でき、製品理解が深まりました。"
            "提案したアイデアが採用され、実際に機能として実装されたのは大きな達成感でした。"
        ),
    },
    {
        "company": "フィンテックアドバンス株式会社",
        "company_page": (
            "金融×テクノロジーで革新的なサービスを提供し、社会のインフラを支えています。"
            "高度なセキュリティ基準のもと、最先端の開発に携われます。"
            "インターンも本番環境に近い開発経験ができます。"
        ),
        "intern_report": (
            "セキュリティ規定が厳しく、開発環境の制約が多くて作業効率が悪かったです。"
            "本番に近い環境とは言え、インターンは検証環境のみのアクセスでした。"
            "金融サービスならではの厳密さは学べましたが、自由度の低さにストレスを感じました。"
        ),
    },
    {
        "company": "ソーシャルインパクト株式会社",
        "company_page": (
            "社会課題をビジネスで解決する、熱量高い仲間たちと共に働けます。"
            "NPOや行政との協働プロジェクトも多く、多様なステークホルダーと関われます。"
            "インターンから正社員登用実績も多数あります。"
        ),
        "intern_report": (
            "NPOや行政との連携は本当にあり、スケールの大きな仕事ができました。"
            "社員の方の情熱が伝わってきて、自分も社会課題に向き合う意識が高まりました。"
            "インターン後に内定を頂き、現在も選考が継続しています。"
        ),
    },
    {
        "company": "デジタルマーケティング株式会社",
        "company_page": (
            "データドリブンなマーケティングで、クライアントの成長を加速します。"
            "Google・Meta等の最新広告技術を駆使し、ROIを最大化します。"
            "インターンもリアルな広告運用データに触れ、実践的なスキルを習得できます。"
        ),
        "intern_report": (
            "実際の広告アカウントを任せてもらえたのは良かったですが、予算規模が小さかったです。"
            "データ分析は毎日行いましたが、施策提案の機会はあまりありませんでした。"
            "実践的なスキルは確かに身につきましたが、業務範囲が狭く感じました。"
        ),
    },
    {
        "company": "AIリサーチラボ株式会社",
        "company_page": (
            "世界トップレベルの研究者と共に、AGIの実現に向けた最先端研究を行います。"
            "論文の共著者になれるチャンスもあり、アカデミアとの強固なパイプを持ちます。"
            "インターンでも研究の最前線に立てる、刺激的な環境です。"
        ),
        "intern_report": (
            "研究者の方々は優秀でしたが、インターンに与えられたタスクはデータ整備が中心でした。"
            "論文への関与は難しく、実質的にはサポート業務が多かったです。"
            "研究の雰囲気に触れられたのは良かったですが、自分が貢献できた感覚は薄かったです。"
        ),
    },
    {
        "company": "コミュニティプラットフォーム株式会社",
        "company_page": (
            "人と人をつなぐプラットフォームで、温かいコミュニティを育てています。"
            "社内の雰囲気も家族のように温かく、長期的に働きたいと思える職場です。"
            "インターンも即戦力として扱い、チームの一員として迎えます。"
        ),
        "intern_report": (
            "チームの雰囲気は本当に温かく、インターンでも居心地よく働けました。"
            "即戦力とは言われましたが、最初の2週間はほぼ研修で実務は後半でした。"
            "社員の方が親身に指導してくれたのは、非常にありがたかったです。"
        ),
    },
    {
        "company": "ロジスティクスDX株式会社",
        "company_page": (
            "物流業界をDXで変革し、社会インフラの効率化に貢献します。"
            "現場と技術の両方を理解したエンジニアを育て、実務に直結したスキルを習得できます。"
            "インターンも現場視察や倉庫見学など、リアルな業務体験が可能です。"
        ),
        "intern_report": (
            "現場視察は1回のみで、主にオフィスでのデスクワークが中心でした。"
            "物流システムの開発には関わりましたが、現場との距離を感じました。"
            "DXというより既存システムの保守作業が多く、変革感は薄かったです。"
        ),
    },
    {
        "company": "ヘルスケアイノベーション株式会社",
        "company_page": (
            "医療×ITで人々の健康を守る、意義のある仕事ができます。"
            "医師・看護師・エンジニアが協働し、現場のリアルな課題を解決します。"
            "インターンも医療現場の声を直接聞く機会があります。"
        ),
        "intern_report": (
            "医療従事者の方とのミーティングに参加でき、現場のニーズを深く理解できました。"
            "社会的意義を感じながら働ける環境で、モチベーションが高まりました。"
            "医師の方が丁寧に医療知識を教えてくれたのは、非常に貴重な体験でした。"
        ),
    },
    {
        "company": "スポーツアナリティクス株式会社",
        "company_page": (
            "スポーツ×データで選手のパフォーマンスを最大化する、新しい挑戦をしています。"
            "プロスポーツチームとの契約実績があり、実際の試合データを扱えます。"
            "インターンもプロの現場で使われる分析手法を学べます。"
        ),
        "intern_report": (
            "実際のプロチームのデータを扱えたのは大きな魅力でした。"
            "分析手法も実践的で、Pythonとスポーツ統計の両方が身につきました。"
            "スポーツ好きな社員が多く、職場の雰囲気が良かったです。"
        ),
    },
    {
        "company": "シェアリングエコノミー株式会社",
        "company_page": (
            "所有から共有へのパラダイムシフトを牽引する、社会変革型スタートアップです。"
            "ユーザーと運営者の双方にWin-Winの価値を提供するプラットフォームを運営しています。"
            "インターンにもグロースハックの実務経験を積める環境があります。"
        ),
        "intern_report": (
            "グロースに関する業務は確かにありましたが、A/Bテストの設計から実行まで時間がかかりました。"
            "ユーザーインタビューには参加でき、プロダクト思考を鍛えられました。"
            "社会変革というよりはビジネス的な施策が中心で、少しギャップを感じました。"
        ),
    },
]


# ─── CSV 保存 ─────────────────────────────────────────────────────────────────
def save_csv(data: list, path: str = OUTPUT) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
    print(f"[OK] {len(data)} 件を {path} に保存しました")


# ─── メイン ───────────────────────────────────────────────────────────────────
def main():
    if "--scrape" in sys.argv:
        idx = sys.argv.index("--scrape")
        companies = sys.argv[idx + 1:] if idx + 1 < len(sys.argv) else []
        if not companies:
            print("[ERROR] 企業名を指定してください: python collect.py --scrape トヨタ ソニー")
            sys.exit(1)
        results = []
        for company in companies:
            row = scrape_company(company)
            if row:
                results.append(row)
        if results:
            save_csv(results)
        else:
            print("[WARN] 取得できませんでした。サンプルデータを保存します。")
            save_csv(SAMPLE_DATA)
    else:
        print("[INFO] サンプルデータ（20社）を保存します")
        print("       スクレイピングする場合: python collect.py --scrape 企業名1 企業名2")
        save_csv(SAMPLE_DATA)


if __name__ == "__main__":
    main()
