"""
app.py  ─  Day 5-6
Streamlit UI。

起動:
  streamlit run app.py
"""

import streamlit as st
from engine import search

# ─── ページ設定 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="求人スキルマッチング",
    page_icon="🎯",
    layout="centered",
)

# ─── スタイル（最小限のCSS） ──────────────────────────────────────────────────
st.markdown("""
<style>
    .score-bar-bg { background:#e9ecef; border-radius:4px; height:10px; margin-top:4px; }
    .score-bar    { background:linear-gradient(90deg,#4f8ef7,#7f5af0); border-radius:4px; height:10px; }
    .rank-badge   { font-size:1.4rem; font-weight:bold; color:#7f5af0; margin-right:8px; }
</style>
""", unsafe_allow_html=True)

# ─── ヘッダー ─────────────────────────────────────────────────────────────────
st.title("🎯 求人スキルマッチング")
st.caption("持っているスキルを入力すると、マッチする求人をランキング表示します")
st.divider()

# ─── 入力フォーム ─────────────────────────────────────────────────────────────
col_input, col_k = st.columns([3, 1])

with col_input:
    skills = st.text_input(
        "スキルを入力してください",
        placeholder="例: Python Django PostgreSQL Docker",
        label_visibility="visible",
    )

with col_k:
    top_k = st.selectbox("表示件数", options=[3, 5, 10, 20], index=1)

# クイック入力ボタン
st.markdown("**クイック選択:**")
quick_cols = st.columns(5)
presets = ["Python", "機械学習", "React", "AWS", "データ分析"]
for i, preset in enumerate(presets):
    if quick_cols[i].button(preset, use_container_width=True):
        skills = preset

search_clicked = st.button("🔍 検索する", type="primary", use_container_width=True)

# ─── 検索 & 結果表示 ──────────────────────────────────────────────────────────
if search_clicked and skills:
    with st.spinner("マッチング計算中..."):
        results = search(skills, top_k=top_k)

    if results.empty:
        st.warning("該当する求人が見つかりませんでした。別のスキルを試してください。")
    else:
        st.success(f"「{skills}」でマッチした求人 上位 {len(results)} 件")
        st.divider()

        for i, row in results.iterrows():
            rank = i + 1
            score_pct = int(row["score"] * 100)
            bar_width  = min(int(row["score"] * 300), 100)  # px上限100

            with st.container(border=True):
                # タイトル行
                title_col, score_col = st.columns([4, 1])
                with title_col:
                    st.markdown(
                        f'<span class="rank-badge">#{rank}</span>'
                        f'<strong>{row["title"]}</strong>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"🏢 {row['company']}")
                with score_col:
                    score_pct = round(row["score"] * 100, 1)
                    st.metric("マッチ度", f"{score_pct}%")

                # スコアバー
                st.markdown(
                    f'<div class="score-bar-bg">'
                    f'<div class="score-bar" style="width:{bar_width}%"></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # 説明文（折りたたみ）
                if row.get("desc"):
                    with st.expander("求人詳細を見る"):
                        st.write(row["desc"])
                        if row.get("url") and str(row["url"]).startswith("http"):
                            st.markdown(f"[🔗 求人ページを開く]({row['url']})")

elif search_clicked and not skills:
    st.warning("スキルを入力してから検索ボタンを押してください。")

# ─── フッター ─────────────────────────────────────────────────────────────────
st.divider()
st.caption("TF-IDF + コサイン類似度 による求人マッチング | データ: jobs.csv")
