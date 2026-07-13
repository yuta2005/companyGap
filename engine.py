"""
engine.py  ─  IR資料 × プレスリリース 表現ギャップ測定の全ロジック

会社の「決算実態(有価証券報告書等の事実ベース記述)」と
「プレスリリースの見出し・アピール文」の乖離を測定する。
プレスリリースデータではなく EDINET(金融庁)由来の公開データを用いるため、
著作権法30条の4(情報解析目的の利用)の趣旨に沿った設計にしている。

機能:
  - tokenize()          MeCab / fugashi → char n-gram フォールバック
  - calc_gap_score()    TF-IDF + コサイン類似度 → 表現ギャップスコア
  - sentiment_score()   pn-ja.dic（あれば）+ 内蔵辞書で感情スコア
  - extract_keywords()  重要キーワード抽出 (tf / tfidf / textrank 切替可)
  - keyword_diff()      IR資料・プレスリリースそれぞれの特徴語を抽出
  - realness_score()    3指標を重み付け合算(IR誠実度)
  - analyze_company()   1社分の全指標を dict で返す
  - analyze_all()       CSV 全社を分析して DataFrame を返す

使い方:
  python engine.py                  # CSV 全社をランキング表示
  python engine.py A社               # 特定企業を詳細表示
"""

import os
import re
import sys
import csv
import math
from collections import Counter

import numpy as np
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
    "当社", "会社", "企業", "当期", "前期", "事業",  # 全社共通で頻出 → 弁別力低
    "以下", "同様", "とおり", "場合", "本資料", "資料",
    "億円", "兆円", "万円", "万台", "万本", "万人", "年度", "月期", "年月",
    # 情報量の乏しい軽動詞（基本形で登録。〜において/〜を行う 等に由来）
    "おく", "おける", "行う", "いう", "含む", "基づく", "関する", "対する",
    "有する", "通ずる", "応じる", "示す", "用いる", "もつ", "持つ", "よる",
    # 社名表記の断片
    "Inc", "Ltd", "Co", "Corporation", "Limited", "inc", "ltd",
}

TARGET_POS = {"名詞", "動詞", "形容詞"}  # 抽出する品詞

# 複合名詞を構成しうる品詞（名詞 + 接頭辞/接尾辞。UniDic と IPAdic 両対応）
_NOUN_PIECE_POS1 = {"名詞", "接頭辞", "接頭詞", "接尾辞"}
# 複合名詞の構成要素から除外する品詞細分類
_NOUN_PIECE_NG_POS2 = {"数詞", "数", "代名詞", "非自立", "副詞可能"}


def _parse_morphemes(text: str) -> list[tuple[str, str, str, str]]:
    """(surface, pos1, pos2, base_form) のリストを返す（MeCab / fugashi 用）"""
    if _TOKENIZE_MODE == "mecab":
        out = []
        node = _TAGGER.parseToNode(text)
        while node:
            f = node.feature.split(",")
            pos1 = f[0] if f else ""
            pos2 = f[1] if len(f) > 1 else ""
            base = f[6] if len(f) > 6 and f[6] != "*" else node.surface
            if node.surface:
                out.append((node.surface, pos1, pos2, base))
            node = node.next
        return out
    # fugashi (UniDic)
    out = []
    for w in _TAGGER(text):
        pos1 = getattr(w.feature, "pos1", "") or ""
        pos2 = getattr(w.feature, "pos2", "") or ""
        base = getattr(w.feature, "orthBase", None) or w.surface
        out.append((w.surface, pos1, pos2, base))
    return out


def _is_noun_piece(pos1: str, pos2: str) -> bool:
    return pos1 in _NOUN_PIECE_POS1 and pos2 not in _NOUN_PIECE_NG_POS2


def _keep_token(t: str) -> bool:
    if len(t) < 2 or t in _STOPWORDS:
        return False
    if re.fullmatch(r"[0-9０-９.,．，%％]+", t):          # 数値のみ
        return False
    if re.fullmatch(r"[0-9０-９.,．，]+[兆億万千百]?[円台本人株期年月日]*", t):  # 数値+助数詞
        return False
    if re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ]{1,2}", t):        # 短い英字断片 (FY, Q など)
        return False
    return True


def _tokenize_chunk(chunk: str) -> list[str]:
    """空白を含まない1チャンクを形態素解析してトークン化。

    連続する名詞（+接頭辞/接尾辞）は複合語として結合する
    （営業/利益/率 → 営業利益率）。動詞・形容詞は基本形に正規化。
    """
    tokens = []
    compound = ""
    compound_has_noun = False   # 接尾辞のみの結合 (「月期」等) を除外するため
    for surface, pos1, pos2, base in _parse_morphemes(chunk):
        if _is_noun_piece(pos1, pos2):
            compound += surface
            compound_has_noun = compound_has_noun or pos1 == "名詞"
            continue
        if compound:
            if compound_has_noun:
                tokens.append(compound)
            compound = ""
            compound_has_noun = False
        if pos1 in ("動詞", "形容詞") and pos2 not in ("非自立", "非自立可能", "接尾"):
            tokens.append(base)
    if compound and compound_has_noun:
        tokens.append(compound)
    return [t for t in tokens if _keep_token(t)]


def tokenize(text: str) -> list[str]:
    """テキストを形態素解析してトークンリストを返す"""
    if _TOKENIZE_MODE in ("mecab", "fugashi"):
        # 空白区切りで複合語が途切れるよう、チャンク単位で解析する
        tokens = []
        for chunk in re.split(r"[\s　]+", text):
            if chunk:
                tokens.extend(_tokenize_chunk(chunk))
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
# 1.5 定型文（免責事項・著作権表記等）の除去
# ══════════════════════════════════════════════════════════════════════════════
# 決算資料・プレスリリースに頻出する免責文はどの会社にもあり、
# キーワード・類似度の両方を汚染するため、スコア計算前に文単位で除去する。

_BOILERPLATE_RE = re.compile(
    r"投資判断の参考|投資勧誘|将来に関する(?:記述|記載|事項)|将来予測"
    r"|インサイダー取引|金融商品取引法|適時開示|証券取引所に通知"
    r"|フォーム20-F|年次報告書|Copyright|All rights reserved|無断転載"
)


def _strip_boilerplate(text: str) -> str:
    """免責事項などの定型文を含む文を取り除いたテキストを返す"""
    segments = re.split(r"[。\n]", text)
    kept = [s for s in segments if s.strip() and not _BOILERPLATE_RE.search(s)]
    return "。".join(kept)


# ══════════════════════════════════════════════════════════════════════════════
# 2. ギャップスコア（TF-IDF + コサイン類似度）
# ══════════════════════════════════════════════════════════════════════════════

def calc_gap_score(ir_summary: str, press_release: str) -> float:
    """
    IR資料とプレスリリースのコサイン類似度から表現ギャップを算出。
    返値: 0〜100（高いほど建前と本音がズレている）
    """
    if _TOKENIZE_MODE == "chargram":
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
        docs = [ir_summary, press_release]
    else:
        vec = TfidfVectorizer(analyzer="word", token_pattern=None,
                              tokenizer=tokenize, min_df=1)
        docs = [ir_summary, press_release]

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
    # IR/プレスリリース文脈で使われがちな「前向きアピール」語(実態を伴わない場合に乖離を生む)
    "挑戦": 0.5, "加速": 0.5, "革新": 0.6, "最適化": 0.4, "価値創造": 0.6,
    "成長ステージ": 0.6, "戦略的": 0.4, "着実": 0.5, "積極的": 0.4,
    # 決算の事実として現れやすい「ネガティブ」語
    "減益": -0.8, "減少": -0.5, "損失": -0.8, "減損": -0.8, "縮小": -0.6,
    "低迷": -0.7, "悪化": -0.7, "先行き不透明": -0.6,
    # 決算の事実として現れやすい「ポジティブ」語
    "増益": 0.8, "増加": 0.5, "堅調": 0.6, "過去最高": 0.9, "上回った": 0.5,
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
    # 辞書の見出し語は「過去最高」「先行き不透明」など複合語が多く、
    # 形態素トークンとの表層一致ではほぼマッチしないため、
    # 全モード共通で部分文字列検索を用いる。
    scores = [v for w, v in _PN_DICT.items() if w in text]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 3)


# ══════════════════════════════════════════════════════════════════════════════
# 4. キーワード抽出・差分
# ══════════════════════════════════════════════════════════════════════════════

KW_METHODS = ("tfidf", "tf", "textrank")

_BG_CORPUS: list[str] | None = None


def _background_corpus() -> list[str]:
    """IDF 計算用の背景コーパス（jobs.csv の全文書）。なければ空リスト。"""
    global _BG_CORPUS
    if _BG_CORPUS is None:
        _BG_CORPUS = []
        if os.path.exists(CSV_PATH):
            try:
                df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
                for col in ("ir_summary", "press_release"):
                    if col in df.columns:
                        _BG_CORPUS += [
                            _strip_boilerplate(str(x)) for x in df[col].dropna()
                        ]
            except Exception as e:
                print(f"[keywords] 背景コーパスの読込に失敗: {e}")
    return _BG_CORPUS


def _textrank_keywords(tokens: list[str], n: int,
                       window: int = 4, damping: float = 0.85,
                       iters: int = 50) -> list[str]:
    """共起グラフ + PageRank（TextRank）で重要語を返す"""
    vocab: dict[str, int] = {}
    for t in tokens:
        vocab.setdefault(t, len(vocab))
    size = len(vocab)
    if size == 0:
        return []
    W = np.zeros((size, size))
    for i, t in enumerate(tokens):
        for j in range(i + 1, min(i + window, len(tokens))):
            u, v = vocab[t], vocab[tokens[j]]
            if u != v:
                W[u, v] += 1.0
                W[v, u] += 1.0
    col_sum = W.sum(axis=0)
    col_sum[col_sum == 0] = 1.0
    M = W / col_sum
    r = np.full(size, 1.0 / size)
    for _ in range(iters):
        r = (1.0 - damping) / size + damping * (M @ r)
    ranked = sorted(vocab, key=lambda t: r[vocab[t]], reverse=True)
    return ranked[:n]


def extract_keywords(text: str, n: int = 8, method: str = "tfidf") -> list[str]:
    """
    テキストから重要キーワードを上位 n 件返す。

    method:
      - "tfidf"    : jobs.csv 全文書を背景コーパスとした TF-IDF。
                     全社共通語（経営・提供 等）が IDF で自動的に沈む。
      - "tf"       : 単純な出現頻度（比較用ベースライン）
      - "textrank" : 共起グラフ + PageRank
    """
    text = _strip_boilerplate(text)

    if _TOKENIZE_MODE == "chargram":
        # 形態素解析なしのフォールバック: 背景コーパス + 対象文書で char TF-IDF
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3),
                              sublinear_tf=True)
        try:
            docs = _background_corpus() + [text]
            tfidf = vec.fit_transform(docs)
            scores = tfidf[-1].toarray()[0]
            features = vec.get_feature_names_out()
            ranked = np.argsort(scores)[::-1]
            return [features[i] for i in ranked
                    if scores[i] > 0 and len(features[i]) >= 2][:n]
        except Exception:
            return []

    if method == "tf":
        return [w for w, _ in Counter(tokenize(text)).most_common(n)]

    if method == "textrank":
        return _textrank_keywords(tokenize(text), n)

    # tfidf（デフォルト）。lowercase=False で tf/textrank と表示を揃える
    vec = TfidfVectorizer(analyzer="word", token_pattern=None,
                          tokenizer=tokenize, sublinear_tf=True,
                          lowercase=False)
    try:
        docs = _background_corpus() + [text]
        tfidf = vec.fit_transform(docs)
        scores = tfidf[-1].toarray()[0]
        features = vec.get_feature_names_out()
        ranked = np.argsort(scores)[::-1]
        return [features[i] for i in ranked if scores[i] > 0][:n]
    except Exception:
        return []


def keyword_diff(ir_summary: str, press_release: str, n: int = 6,
                 method: str = "tfidf") -> dict:
    """
    IR資料とプレスリリースのキーワード差分を返す。
    - company_only: IR資料にのみ現れる語
    - intern_only : プレスリリースにのみ現れる語
    - common      : 両方で使われている語
    （いずれも重要度順を保持）
    """
    cp_kws = extract_keywords(ir_summary, n=20, method=method)
    pr_kws = extract_keywords(press_release, n=20, method=method)
    cp_set, pr_set = set(cp_kws), set(pr_kws)
    return {
        "company_only": [w for w in cp_kws if w not in pr_set][:n],
        "intern_only":  [w for w in pr_kws if w not in cp_set][:n],
        "common":       [w for w in cp_kws if w in pr_set][:n],
    }


def keyword_match_rate(ir_summary: str, press_release: str,
                       method: str = "tfidf") -> float:
    """キーワードの一致率（0〜1）"""
    cp_kws = set(extract_keywords(ir_summary, n=20, method=method))
    pr_kws = set(extract_keywords(press_release, n=20, method=method))
    if not cp_kws and not pr_kws:
        return 0.5
    union = cp_kws | pr_kws
    inter = cp_kws & pr_kws
    return round(len(inter) / len(union), 3) if union else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. 代表文抽出（最も特徴的な文を1文返す）
# ══════════════════════════════════════════════════════════════════════════════

def _most_representative_sentence(text: str) -> str:
    """LexRank（文間類似度グラフの中心性）で最も代表的な文を返す。

    旧実装（固有語数最大）は長い定型文が選ばれがちだったため、
    「他の多くの文と内容が重なる文 = 文書の中心的な文」を選ぶ方式に変更。
    """
    text = _strip_boilerplate(text)
    sentences = [s.strip() for s in re.split(r"[。．\n]", text) if len(s.strip()) > 10]
    if not sentences:
        return text[:60]
    if len(sentences) == 1:
        return sentences[0]

    if _TOKENIZE_MODE == "chargram":
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
    else:
        vec = TfidfVectorizer(analyzer="word", token_pattern=None,
                              tokenizer=tokenize)
    try:
        tfidf = vec.fit_transform(sentences)
        sim = cosine_similarity(tfidf)
        np.fill_diagonal(sim, 0.0)
        row_sum = sim.sum(axis=1, keepdims=True)
        row_sum[row_sum == 0] = 1.0
        M = sim / row_sum          # 行確率行列
        size = len(sentences)
        r = np.full(size, 1.0 / size)
        damping = 0.85
        for _ in range(50):
            r = (1.0 - damping) / size + damping * (M.T @ r)
        return sentences[int(np.argmax(r))]
    except Exception:
        # ベクトル化に失敗した場合は旧方式（固有語数最大）にフォールバック
        scored = [(s, len(set(tokenize(s)))) for s in sentences]
        return max(scored, key=lambda x: x[1])[0]


# ══════════════════════════════════════════════════════════════════════════════
# 6. IR誠実度スコア（統合指標）
# ══════════════════════════════════════════════════════════════════════════════

def realness_score(gap: float, sentiment: float, kw_match: float) -> float:
    """
    gap       : 0〜100（大 = 乖離が大きい）
    sentiment : -1〜+1（正 = ポジティブ体験）
    kw_match  : 0〜1  （大 = キーワード一致）
    返値      : 0〜100（高いほど「会社説明が実態に近い＝信頼できる」）
    """
    w_gap  = 0.5   # ギャップが大きいと大幅減点
    w_sent = 0.3   # プレスリリースがネガティブなら減点
    w_kw   = 0.2   # キーワード不一致なら減点

    gap_norm  = 1.0 - (gap / 100.0)           # 高いほど良い
    sent_norm = (sentiment + 1.0) / 2.0       # 0〜1 に正規化
    raw = gap_norm * w_gap + sent_norm * w_sent + kw_match * w_kw
    return round(raw * 100, 1)


# ══════════════════════════════════════════════════════════════════════════════
# 7. 1社分の全指標を計算
# ══════════════════════════════════════════════════════════════════════════════

def analyze_company(company: str, ir_summary: str, press_release: str,
                    kw_method: str = "tfidf") -> dict:
    """
    Returns
    -------
    dict with keys:
      company, gap_score, sentiment, kw_match, realness,
      kw_diff, rep_ir, rep_press
    """
    # 免責事項などの定型文は全指標を汚染するため最初に除去する
    ir_clean    = _strip_boilerplate(ir_summary)
    press_clean = _strip_boilerplate(press_release)

    gap   = calc_gap_score(ir_clean, press_clean)
    sent  = sentiment_score(press_clean)
    kwm   = keyword_match_rate(ir_clean, press_clean, method=kw_method)
    real  = realness_score(gap, sent, kwm)
    diff  = keyword_diff(ir_clean, press_clean, method=kw_method)
    return {
        "company":     company,
        "gap_score":   gap,
        "sentiment":   sent,
        "kw_match":    round(kwm * 100, 1),
        "realness":    real,
        "kw_ir":  diff["company_only"],
        "kw_press":   diff["intern_only"],
        "kw_common":   diff["common"],
        "rep_ir": _most_representative_sentence(ir_clean),
        "rep_press":  _most_representative_sentence(press_clean),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. CSV 全社を分析
# ══════════════════════════════════════════════════════════════════════════════

def analyze_all(csv_path: str = CSV_PATH, kw_method: str = "tfidf") -> pd.DataFrame:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"[ERROR] {csv_path} が見つかりません。python collect.py を実行してください。"
        )
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    results = []
    for _, row in df.iterrows():
        r = analyze_company(
            str(row.get("company", "")),
            str(row.get("ir_summary", "")),
            str(row.get("press_release", "")),
            kw_method=kw_method,
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
            df_raw = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
            for _, r in match.iterrows():
                print(f"\n{'='*60}")
                print(f"  {r['company']}")
                print(f"{'='*60}")
                print(f"  表現ギャップスコア  : {r['gap_score']:.1f} / 100")
                print(f"  感情スコア    : {r['sentiment']:+.3f}  (正=ポジ / 負=ネガ)")
                print(f"  KW一致率      : {r['kw_match']:.1f}%")
                print(f"  IR誠実度  : {r['realness']:.1f} / 100")
                print(f"\n  [IR資料代表文]")
                print(f"  {r['rep_ir']}")
                print(f"\n  [プレスリリース代表文]")
                print(f"  {r['rep_press']}")
                print(f"\n  [IR資料固有KW] {r['kw_ir']}")
                print(f"  [プレスリリース固有KW    ] {r['kw_press']}")

                # キーワード抽出手法の比較（TF / TF-IDF / TextRank）
                raw = df_raw[df_raw["company"] == r["company"]]
                if not raw.empty:
                    ir_text = str(raw.iloc[0]["ir_summary"])
                    pr_text = str(raw.iloc[0]["press_release"])
                    print(f"\n  [キーワード抽出手法の比較]")
                    for m in KW_METHODS:
                        print(f"    IR資料 {m:>8}: {extract_keywords(ir_text, n=8, method=m)}")
                    for m in KW_METHODS:
                        print(f"    プレス {m:>8}: {extract_keywords(pr_text, n=8, method=m)}")
            sys.exit(0)

    # 全社ランキング
    print(f"\n{'社名':<28} {'表現ギャップ':>6}  {'感情':>6}  {'KW一致':>6}  {'リアル度':>7}")
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
