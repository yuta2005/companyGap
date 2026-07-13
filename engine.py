"""
engine.py  ─  Day 3-4
TF-IDF + コサイン類似度で求人をランキングするコアロジック。

使い方:
  python engine.py                         # デフォルト検索（Python Django SQL）
  python engine.py "機械学習 PyTorch NLP"  # 引数でスキルを指定
"""

import sys
import os
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── 設定 ─────────────────────────────────────────────────────────────────────
CSV_PATH = os.path.join(os.path.dirname(__file__), "jobs.csv")


# ─── データ読み込み & ベクトル化 ───────────────────────────────────────────────
def _load_and_fit(csv_path: str = CSV_PATH):
    """CSVを読んでTF-IDFモデルをフィットする。モジュール読み込み時に1回だけ実行。"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"[ERROR] {csv_path} が見つかりません。\n"
            "   先に   python collect.py   を実行してください。"
        )

    df = pd.read_csv(csv_path)

    # title + company + desc を結合して検索対象テキストを作る
    df["_text"] = (
        df["title"].fillna("") + " " +
        df["company"].fillna("") + " " +
        df["desc"].fillna("")
    )

    # char n-gram (2〜3文字) → MeCab不要で日本語対応
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
    matrix = vec.fit_transform(df["_text"])

    return df, vec, matrix


# モジュールロード時に1度だけ実行
_df, _vec, _matrix = _load_and_fit()


# ─── 検索関数（外部から呼ぶのはここだけ） ─────────────────────────────────────
def search(user_skills: str, top_k: int = 5) -> pd.DataFrame:
    """
    Parameters
    ----------
    user_skills : str
        スペース区切りのスキル文字列。例: "Python Django SQL"
    top_k : int
        返す件数（デフォルト 5）

    Returns
    -------
    pd.DataFrame
        columns: title, company, score, url, desc
    """
    if not user_skills.strip():
        return pd.DataFrame(columns=["title", "company", "score", "url", "desc"])

    query_vec = _vec.transform([user_skills])
    scores = cosine_similarity(query_vec, _matrix)[0]

    result = _df.copy()
    result["score"] = scores
    result = (
        result
        .nlargest(top_k, "score")
        [["title", "company", "score", "url", "desc"]]
        .reset_index(drop=True)
    )
    return result


# ─── 動作確認用エントリポイント ───────────────────────────────────────────────
if __name__ == "__main__":
    import io
    # Windows コマンドプロンプト対応: UTF-8 出力に切り替える
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    skills = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Python Django SQL"

    print(f"\n[検索] スキル: '{skills}'\n")
    result = search(skills, top_k=5)

    if result.empty:
        print("結果が見つかりませんでした。")
    else:
        for i, row in result.iterrows():
            rank = i + 1
            bar = "=" * int(row["score"] * 40)  # ASCII バー
            print(f"  #{rank}  {row['title']}")
            print(f"       {row['company']}")
            print(f"       スコア: {row['score']:.4f}  [{bar}]")
            print()
