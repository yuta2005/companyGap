"""
app.py  ─  IR資料とプレスリリースの表現ギャップ測定 UI

起動:
  python -m streamlit run app.py
"""

import streamlit as st
import pandas as pd
import os
from engine import analyze_all, analyze_company

# ─── ページ設定 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="IR資料 × プレスリリース 表現ギャップ測定",
    page_icon="🔍",
    layout="wide",
)

# ─── カスタムCSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans JP', sans-serif;
}

.hero {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 16px;
    padding: 2.5rem 2rem;
    margin-bottom: 1.5rem;
    text-align: center;
}
.hero h1 { color: #e2e8f0; font-size: 1.9rem; margin: 0 0 .4rem 0; }
.hero p  { color: #94a3b8; font-size: 1rem; margin: 0; }

.metric-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    text-align: center;
}
.metric-label { color: #94a3b8; font-size: .78rem; margin-bottom: .3rem; }
.metric-value { font-size: 1.7rem; font-weight: 700; }

.kw-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: .8rem;
    margin: 2px;
}
.kw-company { background: #1e3a5f; color: #93c5fd; }
.kw-intern  { background: #3b1f2b; color: #f9a8d4; }
.kw-common  { background: #1e3b2b; color: #6ee7b7; }

.rep-box {
    background: #0f172a;
    border-left: 3px solid #475569;
    border-radius: 4px;
    padding: .6rem 1rem;
    font-size: .88rem;
    color: #cbd5e1;
    margin: .4rem 0;
    font-style: italic;
}
</style>
""", unsafe_allow_html=True)

# ─── ヘッダー ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <h1>🔍 IR資料 × プレスリリース 表現ギャップ測定</h1>
  <p>決算短信・有価証券報告書の事実ベース記述と、プレスリリースのアピール表現のギャップを可視化します</p>
</div>
""", unsafe_allow_html=True)

# ─── データ読み込み ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner="全社を分析中...")
def load_data(kw_method: str):
    return analyze_all(kw_method=kw_method)

# ─── サイドバー ───────────────────────────────────────────────────────────────
_KW_METHOD_LABELS = {
    "TF-IDF（全社コーパスIDF）": "tfidf",
    "TF（出現頻度）": "tf",
    "TextRank（共起グラフ）": "textrank",
}

with st.sidebar:
    st.markdown("### ⚙️ 表示設定")
    view_mode = st.radio("表示モード", ["全社ランキング", "企業詳細分析", "手動入力で分析"])
    kw_label = st.selectbox("キーワード抽出手法", list(_KW_METHOD_LABELS.keys()))
    kw_method = _KW_METHOD_LABELS[kw_label]
    st.divider()

    st.markdown("### 📊 スコア説明")
    st.markdown("""
| スコア | 意味 |
|--------|------|
| **表現ギャップ** | IR資料とプレスリリースのズレ（高=要注意） |
| **感情** | プレスリリースのポジネガ度（正=ポジティブ） |
| **KW一致率** | 共通キーワードの割合 |
| **リアル度** | 総合信頼スコア（高=一致している） |
""")

    st.divider()
    st.caption("MeCab/fugashi が未インストールの場合は char n-gram で動作します。\n\n`python -m streamlit run app.py` で起動してください。")

try:
    df = load_data(kw_method)
except FileNotFoundError as e:
    st.error(str(e))
    st.code("python collect.py", language="bash")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# モード 1: 全社ランキング
# ══════════════════════════════════════════════════════════════════════════════
if view_mode == "全社ランキング":
    st.subheader("🏢 IR誠実度 ランキング（低い順 = 要注意）")

    # サマリメトリクス
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">分析企業数</div>
            <div class="metric-value" style="color:#60a5fa">{len(df)}</div></div>""",
            unsafe_allow_html=True)
    with c2:
        worst = df.iloc[0]
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">最大表現ギャップ</div>
            <div class="metric-value" style="color:#f87171">{df['gap_score'].max():.1f}%</div></div>""",
            unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">平均リアル度</div>
            <div class="metric-value" style="color:#a78bfa">{df['realness'].mean():.1f}</div></div>""",
            unsafe_allow_html=True)
    with c4:
        pos_count = (df["sentiment"] > 0).sum()
        st.markdown(f"""<div class="metric-card">
            <div class="metric-label">ポジティブ体験</div>
            <div class="metric-value" style="color:#34d399">{pos_count}/{len(df)}</div></div>""",
            unsafe_allow_html=True)

    st.divider()

    # 各社カード
    for i, row in df.iterrows():
        rank = i + 1
        real = row["realness"]

        # リアル度に応じた色
        if real < 40:
            bar_color = "#ef4444"
            label_color = "#fca5a5"
            rank_icon = "⚠️"
        elif real < 65:
            bar_color = "#f59e0b"
            label_color = "#fcd34d"
            rank_icon = "🔶"
        else:
            bar_color = "#10b981"
            label_color = "#6ee7b7"
            rank_icon = "✅"

        with st.container():
            col_rank, col_info, col_scores = st.columns([1, 5, 4])

            with col_rank:
                st.markdown(f"""
                <div style="text-align:center; padding:1rem 0;">
                  <div style="font-size:2rem;">{rank_icon}</div>
                  <div style="font-size:1.4rem; font-weight:700; color:{label_color}">#{rank}</div>
                </div>""", unsafe_allow_html=True)

            with col_info:
                st.markdown(f"**{row['company']}**")

                # リアル度バー
                bar_w = int(real)
                st.markdown(f"""
                <div style="background:#1e293b; border-radius:6px; height:12px; margin:.4rem 0;">
                  <div style="background:{bar_color}; width:{bar_w}%; height:12px; border-radius:6px;"></div>
                </div>
                <div style="color:{label_color}; font-size:.85rem;">IR誠実度 {real:.1f} / 100</div>
                """, unsafe_allow_html=True)

                # キーワードピル
                kw_html = ""
                for kw in row["kw_ir"][:4]:
                    kw_html += f'<span class="kw-pill kw-company">{kw}</span>'
                for kw in row["kw_press"][:4]:
                    kw_html += f'<span class="kw-pill kw-intern">{kw}</span>'
                if kw_html:
                    st.markdown(kw_html, unsafe_allow_html=True)

            with col_scores:
                m1, m2, m3 = st.columns(3)
                m1.metric("表現ギャップ", f"{row['gap_score']:.1f}%")
                m2.metric("感情", f"{row['sentiment']:+.2f}")
                m3.metric("KW一致", f"{row['kw_match']:.0f}%")

            with st.expander("代表文・キーワード詳細を見る"):
                left, right = st.columns(2)
                with left:
                    st.markdown("🏢 **IR資料代表文**")
                    st.markdown(f'<div class="rep-box">{row["rep_ir"]}</div>',
                                unsafe_allow_html=True)
                    st.markdown("**IR資料固有KW** （プレスリリースに出てこない語）")
                    pills = "".join([f'<span class="kw-pill kw-company">{k}</span>'
                                     for k in row["kw_ir"]])
                    st.markdown(pills or "（なし）", unsafe_allow_html=True)

                with right:
                    st.markdown("💬 **プレスリリース代表文**")
                    st.markdown(f'<div class="rep-box">{row["rep_press"]}</div>',
                                unsafe_allow_html=True)
                    st.markdown("**プレスリリース固有KW** （IR資料に出てこない語）")
                    pills = "".join([f'<span class="kw-pill kw-intern">{k}</span>'
                                     for k in row["kw_press"]])
                    st.markdown(pills or "（なし）", unsafe_allow_html=True)

                common_pills = "".join([f'<span class="kw-pill kw-common">{k}</span>'
                                        for k in row["kw_common"]])
                if common_pills:
                    st.markdown("**共通KW**")
                    st.markdown(common_pills, unsafe_allow_html=True)

            st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# モード 2: 企業詳細分析
# ══════════════════════════════════════════════════════════════════════════════
elif view_mode == "企業詳細分析":
    st.subheader("🔬 企業詳細分析")
    company_list = df["company"].tolist()
    selected = st.selectbox("企業を選択", company_list)
    row = df[df["company"] == selected].iloc[0]

    # スコアカード
    c1, c2, c3, c4 = st.columns(4)
    real = row["realness"]
    real_color = "#ef4444" if real < 40 else "#f59e0b" if real < 65 else "#10b981"

    c1.metric("🎯 IR誠実度", f"{real:.1f} / 100")
    c2.metric("📏 表現ギャップスコア", f"{row['gap_score']:.1f}%",
              delta=f"{50 - row['gap_score']:.1f}% vs 平均",
              delta_color="inverse")
    c3.metric("💭 感情スコア", f"{row['sentiment']:+.3f}")
    c4.metric("🔑 キーワード一致率", f"{row['kw_match']:.1f}%")

    st.divider()

    # リアル度ゲージ
    bar_w = int(real)
    st.markdown(f"""
    <div style="background:#1e293b; border-radius:8px; height:20px;">
      <div style="background:{real_color}; width:{bar_w}%; height:20px; border-radius:8px;
           transition: width 0.8s ease;"></div>
    </div>
    <div style="text-align:center; color:{real_color}; margin-top:.4rem; font-weight:600;">
      IR誠実度 {real:.1f} / 100
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    left, right = st.columns(2)
    with left:
        st.markdown("#### 🏢 IR資料")
        st.markdown(f'<div class="rep-box">{row["rep_ir"]}</div>', unsafe_allow_html=True)
        st.markdown("**IR資料固有キーワード**（建前ワード）")
        pills = "".join([f'<span class="kw-pill kw-company">{k}</span>'
                         for k in row["kw_ir"]])
        st.markdown(pills or "（抽出できませんでした）", unsafe_allow_html=True)

    with right:
        st.markdown("#### 💬 プレスリリース")
        st.markdown(f'<div class="rep-box">{row["rep_press"]}</div>', unsafe_allow_html=True)
        st.markdown("**プレスリリース固有キーワード**（本音ワード）")
        pills = "".join([f'<span class="kw-pill kw-intern">{k}</span>'
                         for k in row["kw_press"]])
        st.markdown(pills or "（抽出できませんでした）", unsafe_allow_html=True)

    if row["kw_common"]:
        st.divider()
        st.markdown("**共通キーワード**（両方に登場する語）")
        pills = "".join([f'<span class="kw-pill kw-common">{k}</span>'
                         for k in row["kw_common"]])
        st.markdown(pills, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# モード 3: 手動入力で分析
# ══════════════════════════════════════════════════════════════════════════════
elif view_mode == "手動入力で分析":
    st.subheader("✍️ テキストを直接入力して分析")
    st.caption("IR資料(決算短信・有価証券報告書)のコピーと、プレスリリースのコピーを貼り付けてください")

    col1, col2 = st.columns(2)
    with col1:
        company_name = st.text_input("企業名", placeholder="例: 株式会社〇〇")
        ir_text = st.text_area(
            "IR資料のテキスト",
            height=220,
            placeholder="決算短信・有価証券報告書から文章をコピー＆ペーストしてください...",
        )
    with col2:
        st.markdown("")  # spacing
        press_text = st.text_area(
            "プレスリリースのテキスト",
            height=220,
            placeholder="企業公式IRページのプレスリリースをコピー＆ペーストしてください...",
        )

    if st.button("🔍 表現ギャップを測定する", type="primary", use_container_width=True):
        if not ir_text.strip() or not press_text.strip():
            st.warning("両方のテキストを入力してください。")
        else:
            with st.spinner("分析中..."):
                result = analyze_company(
                    company_name or "入力企業",
                    ir_text,
                    press_text,
                    kw_method=kw_method,
                )

            real = result["realness"]
            real_color = "#ef4444" if real < 40 else "#f59e0b" if real < 65 else "#10b981"
            verdict = "⚠️ 要注意（大きな乖離あり）" if real < 40 else "🔶 やや乖離あり" if real < 65 else "✅ 概ね一致しています"

            st.success(f"{verdict} — IR誠実度: **{real:.1f} / 100**")

            c1, c2, c3 = st.columns(3)
            c1.metric("表現ギャップスコア", f"{result['gap_score']:.1f}%")
            c2.metric("プレスリリースの感情", f"{result['sentiment']:+.3f}")
            c3.metric("KW一致率", f"{result['kw_match']:.1f}%")

            st.divider()
            left, right = st.columns(2)
            with left:
                st.markdown("🏢 **IR資料代表文**")
                st.markdown(f'<div class="rep-box">{result["rep_ir"]}</div>', unsafe_allow_html=True)
                st.markdown("**IR資料固有KW**")
                pills = "".join([f'<span class="kw-pill kw-company">{k}</span>'
                                 for k in result["kw_ir"]])
                st.markdown(pills or "（なし）", unsafe_allow_html=True)

            with right:
                st.markdown("💬 **プレスリリース代表文**")
                st.markdown(f'<div class="rep-box">{result["rep_press"]}</div>', unsafe_allow_html=True)
                st.markdown("**プレスリリース固有KW**")
                pills = "".join([f'<span class="kw-pill kw-intern">{k}</span>'
                                 for k in result["kw_press"]])
                st.markdown(pills or "（なし）", unsafe_allow_html=True)

# ─── フッター ─────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "TF-IDF + コサイン類似度 / 感情極性辞書 / キーワード差分 による表現ギャップ測定 | "
    "起動: `python -m streamlit run app.py`"
)
