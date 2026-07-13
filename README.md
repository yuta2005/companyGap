# 🎯 Skill Matcher — 求人スキルマッチング検索

スキルを入力すると **TF-IDF + コサイン類似度** で求人をランキング表示する Web アプリです。

---

## 🚀 起動手順

```bash
# 1. 依存パッケージをインストール
pip install -r requirements.txt

# 2. 求人データを生成（サンプル20件）
python collect.py

# 3. ロジックだけ確認したい場合
python engine.py "Python Django SQL"

# 4. Web UI を起動
streamlit run app.py
```

ブラウザが自動で開き `http://localhost:8501` にアクセスできます。

---

## 🗂 ファイル構成

```
skill_matcher/
├── collect.py        # Day1-2: 求人票を jobs.csv に保存
├── engine.py         # Day3-4: TF-IDF + コサイン類似度検索
├── app.py            # Day5-6: Streamlit UI
├── jobs.csv          # 求人データ（collect.py で生成）
└── requirements.txt  # 依存パッケージ一覧
```

---

## ⚙️ 仕組み

| ステップ | 内容 |
|----------|------|
| データ収集 | `collect.py` でサンプルデータ or スクレイピング → `jobs.csv` |
| ベクトル化 | `TfidfVectorizer(analyzer="char_wb", ngram_range=(2,3))` で日本語対応（MeCab不要） |
| 検索 | ユーザー入力スキルと各求人のコサイン類似度を計算 |
| 表示 | Streamlit でランキング + スコアバーを表示 |

---

## 📦 依存パッケージ

```
pandas
scikit-learn
streamlit
requests
beautifulsoup4
```

---

## 🔧 カスタマイズ

- **求人データを増やす**: `jobs.csv` に行を追加するだけで自動的にランキングに反映されます
- **実際の求人を取得**: `python collect.py --scrape エンジニア` で求人ボックスからスクレイピングを試みます（サイト構造によっては手動調整が必要）
- **表示件数**: アプリ上のセレクトボックスで 3 / 5 / 10 / 20 件を切り替えられます
