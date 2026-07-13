"""
engine.py  ─  乖離度測定の全ロジック

機能:
  - tokenize()          MeCab / fugashi → char n-gram フォールバック
  - calc_gap_score()    TF-IDF + コサイン類似度 → ギャップスコア
  - sentiment_score()   pn-ja.dic（あれば）+ 内蔵辞書で感情スコア
  - keyword_diff()      会社ページ・体験記それぞれの特徴語を抽出
  - realness_score()    3指標を重み付け合算
  - analyze_company()   1社分の全指標を dict で返す
  - analyze_all()       CSV 全社を分析して DataFrame を返す

使い方:
  python engine.py                  # CSV 全社をランキング表示
  python engine.py グロースビジョン  # 特定企業を詳細表示
"""

import os
import re
import sys
import csv
import math
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CSV_PATH = os.path.join(os.path.dirname(__file__), "jobs.csv")
PN_DIC_PATH = os.path.join(os.path.dirname(__file__), "pn-ja.dic")

# ══════════════════════════════════════════════════════════════════════════════
# 1. 形態素解析（MeCab → fugashi → char n-gram フォールバック）
# ══════════════════════════════════════════════════════════════════════════════

_TAGGER = None
_TOKENIZE_MODE = "chargram"   # "mecab" | "fugashi" | "chargram"

def _init_tagger():
    global _TAGGER, _TOKENIZE_MODE
    # MeCab を試みる
    try:
        import MeCab
        _TAGGER = MeCab.Tagger()
        _TOKENIZE_MODE = "mecab"
        print("[tokenizer] MeCab を使用します")
        return
    except Exception:
        pass
    # fugashi を試みる
    try:
        import fugashi
        _TAGGER = fugashi.Tagger()
        _TOKENIZE_MODE = "fugashi"
        print("[tokenizer] fugashi を使用します")
        return
    except Exception:
        pass
    # フォールバック: 文字 n-gram
    print("[tokenizer] MeCab/fugashi 未インストール -> char n-gram を使用します")
    _TOKENIZE_MODE = "chargram"

_init_tagger()

# 除外するストップワード
_STOPWORDS = {
    "の", "に", "は", "を", "が", "で", "と", "も", "や", "へ", "から", "より",
    "て", "し", "た", "い", "な", "こと", "もの", "ため", "よう", "あり", "でき",
    "いる", "する", "ある", "なる", "れる", "られる", "ます", "です", "ない",
    "その", "この", "それ", "これ", "あの", "ご", "お", "さ", "ん", "か",
    "インターン", "会社", "企業", "仕事", "業務", "社員",  # 全社共通で頻出 → 弁別力低
}

TARGET_POS = {"名詞", "動詞", "形容詞"}  # 抽出する品詞

def tokenize(text: str) -> list[str]:
    """テキストを形態素解析してトークンリストを返す"""
    if _TOKENIZE_MODE == "mecab":
        node = _TAGGER.parseToNode(text)
        tokens = []
        while node:
            feature = node.feature.split(",")
            pos = feature[0]
            surface = node.surface
            if pos in TARGET_POS and surface not in _STOPWORDS and len(surface) > 1:
                tokens.append(surface)
            node = node.next
        return tokens

    if _TOKENIZE_MODE == "fugashi":
        tokens = []
        for word in _TAGGER(text):
            pos = word.feature.pos1 if hasattr(word.feature, "pos1") else ""
            surface = word.surface
            if pos in TARGET_POS and surface not in _STOPWORDS and len(surface) > 1:
                tokens.append(surface)
        return tokens

    # char n-gram（2〜4文字の部分文字列。MeCab なしでも日本語に有効）
    text_clean = re.sub(r"[^\u3040-\u9FFF\u30A0-\u30FF\u4E00-\u9FFF]", " ", text)
    tokens = []
    for chunk in text_clean.split():
        for n in (2, 3):
            tokens += [chunk[i:i+n] for i in range(len(chunk) - n + 1)]
    return [t for t in tokens if t not in _STOPWORDS]


def _join_tokens(text: str) -> str:
    """tokenize して 空白結合（TfidfVectorizer の analyzer='word' 用）"""
    return " ".join(tokenize(text))


# ══════════════════════════════════════════════════════════════════════════════
# 2. ギャップスコア（TF-IDF + コサイン類似度）
# ══════════════════════════════════════════════════════════════════════════════

def calc_gap_score(company_page: str, intern_report: str) -> float:
    """
    会社ページと体験記のコサイン類似度から乖離度を算出。
    返値: 0〜100（高いほど建前と本音がズレている）
    """
    if _TOKENIZE_MODE == "chargram":
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
        docs = [company_page, intern_report]
    else:
        vec = TfidfVectorizer(analyzer="word", token_pattern=None,
                              tokenizer=tokenize, min_df=1)
        docs = [company_page, intern_report]

    try:
        tfidf = vec.fit_transform(docs)
        similarity = cosine_similarity(tfidf[0], tfidf[1])[0][0]
        return round((1.0 - float(similarity)) * 100, 1)
    except Exception:
        return 50.0   # 計算失敗時は中間値


# ══════════════════════════════════════════════════════════════════════════════
# 3. 感情スコア（pn-ja.dic + 内蔵辞書）
# ══════════════════════════════════════════════════════════════════════════════

# 内蔵の職場感情辞書（pn-ja.dic がなくても動作）
_BUILTIN_PN: dict[str, float] = {
    # ポジティブ
    "充実": 0.8, "やりがい": 0.9, "成長": 0.7, "貴重": 0.7, "刺激": 0.6,
    "達成": 0.8, "感謝": 0.7, "親切": 0.8, "丁寧": 0.7, "温かい": 0.8,
    "楽しい": 0.9, "喜び": 0.8, "信頼": 0.7, "活躍": 0.7, "挑戦": 0.5,
    "自由": 0.6, "柔軟": 0.6, "スキル": 0.5, "学び": 0.7, "熱量": 0.6,
    "共感": 0.7, "明確": 0.6, "サポート": 0.6, "採用": 0.4,
    # ネガティブ
    "残業": -0.8, "辛い": -0.9, "困難": -0.6, "違和感": -0.7, "不満": -0.8,
    "ストレス": -0.9, "不明確": -0.7, "狭い": -0.4, "限られた": -0.5,
    "少ない": -0.5, "却下": -0.8, "形式的": -0.6, "制約": -0.6,
    "古い": -0.5, "保守": -0.3, "繰り返し": -0.5, "プレッシャー": -0.5,
    "難しい": -0.4, "薄い": -0.4, "弱い": -0.4, "乏しい": -0.6,
}

def _load_pn_dic(path: str = PN_DIC_PATH) -> dict[str, float]:
    """
    pn-ja.dic（東北大感情極性辞書）を読み込む。
    フォーマット: 単語\t読み\t品詞\tスコア
    """
    if not os.path.exists(path):
        return {}
    pn = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                try:
                    pn[parts[0]] = float(parts[3])
                except ValueError:
                    pass
    print(f"[pn-ja] {len(pn)} 語を読み込みました")
    return pn

_PN_DICT: dict[str, float] = {**_BUILTIN_PN, **_load_pn_dic()}


def sentiment_score(text: str) -> float:
    """
    テキストの感情スコアを返す。
    返値: -1.0〜+1.0（正: ポジティブ体験 / 負: ネガティブ体験）
    """
    if _TOKENIZE_MODE != "chargram":
        tokens = tokenize(text)
    else:
        # char n-gram モードでは辞書の語を直接テキスト内検索
        tokens = list(_PN_DICT.keys())
        tokens = [t for t in tokens if t in text]

    scores = [_PN_DICT[t] for t in tokens if t in _PN_DICT]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 3)


# ══════════════════════════════════════════════════════════════════════════════
# 4. キーワード抽出・差分
# ══════════════════════════════════════════════════════════════════════════════

def _top_keywords(text: str, n: int = 8) -> list[str]:
    """TF-IDF で上位キーワードを返す（単文書 → IDF は対数で代替）"""
    if _TOKENIZE_MODE == "chargram":
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), max_features=200)
    else:
        vec = TfidfVectorizer(analyzer="word", token_pattern=None,
                              tokenizer=tokenize, max_features=200)
    try:
        # 複数文に分割して疑似コーパスを作る
        sentences = re.split(r"[。．\n]", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < 2:
            sentences = [text, text]  # 文が1つしかない場合のダミー
        tfidf = vec.fit_transform(sentences)
        scores = tfidf.sum(axis=0).A1
        features = vec.get_feature_names_out()
        ranked = sorted(zip(features, scores), key=lambda x: x[1], reverse=True)
        # 読みやすさのため3文字以上の語を優先（char n-gram では短すぎるものを除外）
        kws = [w for w, _ in ranked if len(w) >= 2][:n]
        return kws
    except Exception:
        return []


def keyword_diff(company_page: str, intern_report: str, n: int = 6) -> dict:
    """
    会社ページと体験記のキーワード差分を返す。
    - company_only: 会社が強調しているがインターンが言及しない語
    - intern_only : インターンが言及するが会社が触れない語
    - common      : 両方で使われている語
    """
    cp_kws = set(_top_keywords(company_page, n=20))
    ir_kws = set(_top_keywords(intern_report, n=20))
    company_only = list(cp_kws - ir_kws)[:n]
    intern_only  = list(ir_kws - cp_kws)[:n]
    common       = list(cp_kws & ir_kws)[:n]
    return {
        "company_only": company_only,
        "intern_only":  intern_only,
        "common":       common,
    }


def keyword_match_rate(company_page: str, intern_report: str) -> float:
    """キーワードの一致率（0〜1）"""
    cp_kws = set(_top_keywords(company_page, n=20))
    ir_kws = set(_top_keywords(intern_report, n=20))
    if not cp_kws and not ir_kws:
        return 0.5
    union  = cp_kws | ir_kws
    inter  = cp_kws & ir_kws
    return round(len(inter) / len(union), 3) if union else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. 代表文抽出（最も特徴的な文を1文返す）
# ══════════════════════════════════════════════════════════════════════════════

def _most_representative_sentence(text: str) -> str:
    """テキスト中で最も情報密度が高い（文字数 × 固有語数）文を返す"""
    sentences = [s.strip() for s in re.split(r"[。．]", text) if len(s.strip()) > 5]
    if not sentences:
        return text[:60]
    scored = [(s, len(set(tokenize(s)))) for s in sentences]
    return max(scored, key=lambda x: x[1])[0]


# ══════════════════════════════════════════════════════════════════════════════
# 6. 社風リアル度スコア（統合指標）
# ══════════════════════════════════════════════════════════════════════════════

def realness_score(gap: float, sentiment: float, kw_match: float) -> float:
    """
    gap       : 0〜100（大 = 乖離が大きい）
    sentiment : -1〜+1（正 = ポジティブ体験）
    kw_match  : 0〜1  （大 = キーワード一致）
    返値      : 0〜100（高いほど「会社説明が実態に近い＝信頼できる」）
    """
    w_gap  = 0.5   # ギャップが大きいと大幅減点
    w_sent = 0.3   # 体験記がネガティブなら減点
    w_kw   = 0.2   # キーワード不一致なら減点

    gap_norm  = 1.0 - (gap / 100.0)           # 高いほど良い
    sent_norm = (sentiment + 1.0) / 2.0       # 0〜1 に正規化
    raw = gap_norm * w_gap + sent_norm * w_sent + kw_match * w_kw
    return round(raw * 100, 1)


# ══════════════════════════════════════════════════════════════════════════════
# 7. 1社分の全指標を計算
# ══════════════════════════════════════════════════════════════════════════════

def analyze_company(company: str, company_page: str, intern_report: str) -> dict:
    """
    Returns
    -------
    dict with keys:
      company, gap_score, sentiment, kw_match, realness,
      kw_diff, rep_company, rep_intern
    """
    gap   = calc_gap_score(company_page, intern_report)
    sent  = sentiment_score(intern_report)
    kwm   = keyword_match_rate(company_page, intern_report)
    real  = realness_score(gap, sent, kwm)
    diff  = keyword_diff(company_page, intern_report)
    return {
        "company":     company,
        "gap_score":   gap,
        "sentiment":   sent,
        "kw_match":    round(kwm * 100, 1),
        "realness":    real,
        "kw_company":  diff["company_only"],
        "kw_intern":   diff["intern_only"],
        "kw_common":   diff["common"],
        "rep_company": _most_representative_sentence(company_page),
        "rep_intern":  _most_representative_sentence(intern_report),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. CSV 全社を分析
# ══════════════════════════════════════════════════════════════════════════════

def analyze_all(csv_path: str = CSV_PATH) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"[ERROR] {csv_path} が見つかりません。python collect.py を実行してください。"
        )
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    results = []
    for _, row in df.iterrows():
        r = analyze_company(
            str(row.get("company", "")),
            str(row.get("company_page", "")),
            str(row.get("intern_report", "")),
        )
        results.append(r)
    result_df = pd.DataFrame(results)
    result_df.sort_values("realness", ascending=True, inplace=True)
    result_df.reset_index(drop=True, inplace=True)
    return result_df


# ══════════════════════════════════════════════════════════════════════════════
# 9. CLI エントリポイント
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    target = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""

    df_all = analyze_all()

    if target:
        # 特定企業の詳細表示
        match = df_all[df_all["company"].str.contains(target)]
        if match.empty:
            print(f"[WARN] '{target}' が見つかりません。全社ランキングを表示します。")
        else:
            for _, r in match.iterrows():
                print(f"\n{'='*60}")
                print(f"  {r['company']}")
                print(f"{'='*60}")
                print(f"  乖離度スコア  : {r['gap_score']:.1f} / 100")
                print(f"  感情スコア    : {r['sentiment']:+.3f}  (正=ポジ / 負=ネガ)")
                print(f"  KW一致率      : {r['kw_match']:.1f}%")
                print(f"  社風リアル度  : {r['realness']:.1f} / 100")
                print(f"\n  [会社ページ代表文]")
                print(f"  {r['rep_company']}")
                print(f"\n  [体験記代表文]")
                print(f"  {r['rep_intern']}")
                print(f"\n  [会社ページ固有KW] {r['kw_company']}")
                print(f"  [体験記固有KW    ] {r['kw_intern']}")
            sys.exit(0)

    # 全社ランキング
    print(f"\n{'社名':<28} {'乖離度':>6}  {'感情':>6}  {'KW一致':>6}  {'リアル度':>7}")
    print("-" * 64)
    for _, r in df_all.iterrows():
        print(
            f"  {r['company']:<26} "
            f"{r['gap_score']:>5.1f}%  "
            f"{r['sentiment']:>+6.3f}  "
            f"{r['kw_match']:>5.1f}%  "
            f"{r['realness']:>6.1f}/100"
        )
    print()
