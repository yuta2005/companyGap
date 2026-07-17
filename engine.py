# -*- coding: utf-8 -*-
"""
engine.py  ─  IR資料 × プレスリリース 表現ギャップ測定の全ロジック

会社の「決算実態(有価証券報告書等の事実ベース記述)」と
「プレスリリースの見出し・アピール文」の乖離を測定する。
当初案の体験記サイトのデータではなく、EDINET(金融庁)の法定開示情報と
企業自身が公開する広報文を情報解析目的で用いるため、
著作権法30条の4(情報解析のための利用)の趣旨に沿った設計にしている。

機能:
  - tokenize()          形態素解析 (fugashi = MeCab + UniDic辞書)
  - calc_gap_score()    TF-IDF + コサイン類似度 → 表現ギャップスコア
  - extract_keywords()  重要キーワード抽出 (TF-IDF)
  - keyword_diff()      IR資料・プレスリリースそれぞれの特徴語を抽出
  - realness_score()    2指標を重み付け合算(IR誠実度)
  - analyze_company()   1社分の全指標を dict で返す
  - analyze_all()       CSV 全社を分析して DataFrame を返す

使い方:
  python engine.py                  # CSV 全社をランキング表示
  python engine.py A社               # 特定企業を詳細表示
"""

import os
import re
import sys

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CSV_PATH = os.path.join(os.path.dirname(__file__), "jobs.csv")

# ══════════════════════════════════════════════════════════════════════════════
# 1. 形態素解析
# ══════════════════════════════════════════════════════════════════════════════

try:
    import fugashi
except ImportError as e:
    raise SystemExit(
        "[ERROR] fugashi が見つかりません。"
        "`pip install -r requirements.txt` で fugashi と unidic-lite を"
        "インストールしてください。"
    ) from e

_TAGGER = fugashi.Tagger()

# 除外するストップワード
_STOPWORDS = {
    "の",
    "に",
    "は",
    "を",
    "が",
    "で",
    "と",
    "も",
    "や",
    "へ",
    "から",
    "より",
    "て",
    "し",
    "た",
    "い",
    "な",
    "こと",
    "もの",
    "ため",
    "よう",
    "あり",
    "でき",
    "いる",
    "する",
    "ある",
    "なる",
    "れる",
    "られる",
    "ます",
    "です",
    "ない",
    "その",
    "この",
    "それ",
    "これ",
    "あの",
    "ご",
    "お",
    "さ",
    "ん",
    "か",
    "当社",
    "会社",
    "企業",
    "当期",
    "前期",
    "事業",  # 全社共通で頻出 → 弁別力低
    "以下",
    "同様",
    "とおり",
    "場合",
    "本資料",
    "資料",
    "億円",
    "兆円",
    "万円",
    "万台",
    "万本",
    "万人",
    "年度",
    "月期",
    "年月",
    # 情報量の乏しい軽動詞（基本形で登録。〜において/〜を行う 等に由来）
    "おく",
    "おける",
    "行う",
    "いう",
    "含む",
    "基づく",
    "関する",
    "対する",
    "有する",
    "通ずる",
    "応じる",
    "示す",
    "用いる",
    "もつ",
    "持つ",
    "よる",
    # 社名表記の断片
    "Inc",
    "Ltd",
    "Co",
    "Corporation",
    "Limited",
    "inc",
    "ltd",
}

# 複合名詞を構成しうる品詞（名詞 + 接頭辞/接尾辞。UniDic の品詞体系）
_NOUN_PIECE_POS1 = {"名詞", "接頭辞", "接尾辞"}
# 複合名詞の構成要素から除外する品詞細分類
_NOUN_PIECE_NG_POS2 = {"数詞", "代名詞"}


def _parse_morphemes(text: str) -> list[tuple[str, str, str, str]]:
    """(surface, pos1, pos2, base_form) のリストを返す"""
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
    if re.fullmatch(r"[0-9０-９.,．，%％]+", t):  # 数値のみ
        return False
    if re.fullmatch(
        r"[0-9０-９.,．，]+[兆億万千百]?[円台本人株期年月日]*", t
    ):  # 数値+助数詞
        return False
    if re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ]{1,2}", t):  # 短い英字断片 (FY, Q など)
        return False
    return True


def _tokenize_chunk(chunk: str, split_compounds: bool = False) -> list[str]:
    """空白を含まない1チャンクを形態素解析してトークン化。

    連続する名詞（+接頭辞/接尾辞）は複合語として結合する
    （営業/利益/率 → 営業利益率）。動詞・形容詞は基本形に正規化。
    split_compounds=True の場合、複合語に加えて構成名詞も出力する
    （海外向け販売 → 海外向け販売, 海外, 販売）。類似度計算用。
    """
    tokens = []
    compound = ""
    compound_has_noun = False  # 接尾辞のみの結合 (「月期」等) を除外するため
    pieces = []  # 複合語を構成する名詞片（split_compounds 用）
    for surface, pos1, pos2, base in _parse_morphemes(chunk):
        if _is_noun_piece(pos1, pos2):
            compound += surface
            compound_has_noun = compound_has_noun or pos1 == "名詞"
            if pos1 == "名詞":
                pieces.append(surface)
            continue
        if compound:
            if compound_has_noun:
                tokens.append(compound)
                if split_compounds and len(pieces) >= 2:
                    tokens.extend(pieces)
            compound = ""
            compound_has_noun = False
            pieces = []
        if pos1 in ("動詞", "形容詞") and pos2 != "非自立可能":
            tokens.append(base)
    if compound and compound_has_noun:
        tokens.append(compound)
        if split_compounds and len(pieces) >= 2:
            tokens.extend(pieces)
    return [t for t in tokens if _keep_token(t)]


def tokenize(text: str, split_compounds: bool = False) -> list[str]:
    """テキストを形態素解析してトークンリストを返す"""
    # 空白区切りで複合語が途切れるよう、チャンク単位で解析する
    tokens = []
    for chunk in re.split(r"[\s　]+", text):
        if chunk:
            tokens.extend(_tokenize_chunk(chunk, split_compounds))
    return tokens


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
# TF-IDF の重みは
# w(t, d) = tf(t, d) × idf(t),   idf(t) = log(N / df(t)) + 1
# に合わせる。sklearn の既定は平滑化 idf（smooth_idf=True →
# log((1+N)/(1+df))+1）のため、全 TfidfVectorizer で smooth_idf=False を
# 指定して上の式と一致させる。tf も生の頻度を使う
# （sublinear_tf は使わない）。


def _tokenize_split(text: str) -> list[str]:
    """類似度計算用トークナイザ。複合語とその構成名詞の両方を素性にする
    （「海外向け販売」と「海外売上」が「海外」で部分一致できるように）。"""
    return tokenize(text, split_compounds=True)


def calc_gap_score(ir_summary: str, press_release: str) -> float:
    """
    IR資料とプレスリリースの TF-IDF コサイン類似度から表現ギャップを算出。
    返値: 0〜100（高いほど建前と本音がズレている）
    """
    try:
        vec = TfidfVectorizer(
            analyzer="word",
            token_pattern=None,
            tokenizer=_tokenize_split,
            min_df=1,
            smooth_idf=False,
        )
        tfidf = vec.fit_transform([ir_summary, press_release])
        similarity = float(cosine_similarity(tfidf[0], tfidf[1])[0][0])
        return round((1.0 - similarity) * 100, 1)
    except Exception:
        return 50.0  # 計算失敗時は中間値


# ══════════════════════════════════════════════════════════════════════════════
# 3. キーワード抽出・差分
# ══════════════════════════════════════════════════════════════════════════════

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


def extract_keywords(text: str, n: int = 8) -> list[str]:
    """
    テキストから重要キーワードを上位 n 件返す。
    jobs.csv 全文書を背景コーパスとした TF-IDF
    （講義の式 w=tf×idf, idf=log(N/df)+1。smooth_idf=False で一致させる）。
    全社共通語（経営・提供 等）は IDF で自動的に沈む。
    """
    text = _strip_boilerplate(text)

    vec = TfidfVectorizer(
        analyzer="word",
        token_pattern=None,
        tokenizer=tokenize,
        smooth_idf=False,
        lowercase=False,
    )
    try:
        docs = _background_corpus() + [text]
        tfidf = vec.fit_transform(docs)
        scores = tfidf[-1].toarray()[0]
        features = vec.get_feature_names_out()
        ranked = np.argsort(scores)[::-1]
        return [features[i] for i in ranked if scores[i] > 0][:n]
    except Exception:
        return []


def keyword_diff(ir_summary: str, press_release: str, n: int = 6) -> dict:
    """
    IR資料とプレスリリースのキーワード差分を返す。
    - company_only: IR資料にのみ現れる語
    - intern_only : プレスリリースにのみ現れる語
    - common      : 両方で使われている語
    （いずれも重要度順を保持）
    """
    cp_kws = extract_keywords(ir_summary, n=20)
    pr_kws = extract_keywords(press_release, n=20)
    cp_set, pr_set = set(cp_kws), set(pr_kws)
    return {
        "company_only": [w for w in cp_kws if w not in pr_set][:n],
        "intern_only": [w for w in pr_kws if w not in cp_set][:n],
        "common": [w for w in cp_kws if w in pr_set][:n],
    }


def keyword_match_rate(ir_summary: str, press_release: str) -> float:
    """キーワードの一致率（0〜1）"""
    cp_kws = set(extract_keywords(ir_summary, n=20))
    pr_kws = set(extract_keywords(press_release, n=20))
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

    vec = TfidfVectorizer(
        analyzer="word", token_pattern=None, tokenizer=tokenize, smooth_idf=False
    )
    try:
        tfidf = vec.fit_transform(sentences)
        sim = cosine_similarity(tfidf)
        np.fill_diagonal(sim, 0.0)
        row_sum = sim.sum(axis=1, keepdims=True)
        row_sum[row_sum == 0] = 1.0
        M = sim / row_sum  # 行確率行列
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


def realness_score(gap: float, kw_match: float) -> float:
    """
    gap       : 0〜100（大 = 乖離が大きい）
    kw_match  : 0〜1  （大 = キーワード一致）
    返値      : 0〜100（高いほど「会社説明が実態に近い＝信頼できる」）
    """
    w_gap = 0.7  # ギャップが大きいと大幅減点
    w_kw = 0.3  # キーワード不一致なら減点

    gap_norm = 1.0 - (gap / 100.0)  # 高いほど良い
    raw = gap_norm * w_gap + kw_match * w_kw
    return round(raw * 100, 1)


# ══════════════════════════════════════════════════════════════════════════════
# 7. 1社分の全指標を計算
# ══════════════════════════════════════════════════════════════════════════════


def analyze_company(company: str, ir_summary: str, press_release: str) -> dict:
    """
    Returns
    -------
    dict with keys:
      company, gap_score, kw_match, realness,
      kw_ir, kw_press, kw_common, rep_ir, rep_press
    """
    # 免責事項などの定型文は全指標を汚染するため最初に除去する
    ir_clean = _strip_boilerplate(ir_summary)
    press_clean = _strip_boilerplate(press_release)

    gap = calc_gap_score(ir_clean, press_clean)
    kwm = keyword_match_rate(ir_clean, press_clean)
    real = realness_score(gap, kwm)
    diff = keyword_diff(ir_clean, press_clean)
    return {
        "company": company,
        "gap_score": gap,
        "kw_match": round(kwm * 100, 1),
        "realness": real,
        "kw_ir": diff["company_only"],
        "kw_press": diff["intern_only"],
        "kw_common": diff["common"],
        "rep_ir": _most_representative_sentence(ir_clean),
        "rep_press": _most_representative_sentence(press_clean),
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
            str(row.get("ir_summary", "")),
            str(row.get("press_release", "")),
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

    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

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
                print(f"  表現ギャップスコア  : {r['gap_score']:.1f} / 100")
                print(f"  KW一致率      : {r['kw_match']:.1f}%")
                print(f"  IR誠実度  : {r['realness']:.1f} / 100")
                print(f"\n  [IR資料代表文]")
                print(f"  {r['rep_ir']}")
                print(f"\n  [プレスリリース代表文]")
                print(f"  {r['rep_press']}")
                print(f"\n  [IR資料固有KW] {r['kw_ir']}")
                print(f"  [プレスリリース固有KW    ] {r['kw_press']}")
                print(f"  [共通KW              ] {r['kw_common']}")
            sys.exit(0)

    # 全社ランキング
    print(f"\n{'社名':<28} {'表現ギャップ':>6}  {'KW一致':>6}  {'リアル度':>7}")
    print("-" * 56)
    for _, r in df_all.iterrows():
        print(
            f"  {r['company']:<26} "
            f"{r['gap_score']:>5.1f}%  "
            f"{r['kw_match']:>5.1f}%  "
            f"{r['realness']:>6.1f}/100"
        )
    print()
