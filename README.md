# 🔍 IR資料とプレスリリースの表現ギャップ測定プログラム

企業が有価証券報告書等で開示する「決算の事実」と、プレスリリースが謳う
「前向きなアピール文言」との**表現のギャップを自動測定**するコマンドラインツールです。

> 本プロジェクトは当初、インターン体験記サイト(One Career・就活会議)の
> スクレイピングを想定していましたが、各サイトの利用規約(著作権の
> 会員/運営会社への帰属、無断収集の禁止条項等)を確認した結果、
> 権利侵害リスクが高いと判断し、**EDINET(金融庁)が公開する法定開示情報**
> を用いる方式に変更しました。詳細は本READMEおよびレポートの
> 「データソースの倫理的検討」を参照してください。

---

## 起動手順

```bash
# 1. 依存パッケージをインストール
pip install -r requirements.txt

# 2. サンプルデータを生成(合成データ・5社分)
python collect.py

# 2'. 実データを取得する場合(要EDINET APIキー)
export EDINET_API_KEY="発行されたキー"          # Windows PowerShell: $env:EDINET_API_KEY="発行されたキー"
python collect.py --edinet <EDINETコード>       # 1社のみ
python collect.py --batch companies.csv         # 実在企業10社をまとめて取得(推奨)

# 3. 全社ランキングを表示
python engine.py

# 4. 特定企業の詳細を表示(社名の部分一致)
python engine.py トヨタ
```

---

## 測定する指標

| 指標 | 計算方法 | 意味 |
|------|----------|------|
| **表現ギャップスコア** | 1 − コサイン類似度(TF-IDF) | 高いほどIR資料とプレスリリースの言葉遣いがズレている |
| **KW一致率** | 特徴語(TF-IDF上位語)の重複率 | 低いほど語彙レベルで乖離している |
| **IR誠実度** | 上記2指標の重み付き統合 | 高いほど「プレスリリースが決算実態に近い」 |

```
IR誠実度 = (1 − 表現ギャップ) × 0.7 + KW一致率 × 0.3
```

キーワード抽出は全社コーパスでIDFを計算する **TF-IDF** を用います。
形態素解析には **fugashi**(MeCab の Python バインディング) + **UniDic 辞書**
(unidic-lite)を使用します(必須依存。`pip install -r requirements.txt` で入ります)。
解析時に連続名詞を複合語として結合し（営業利益率・ゲーム専用機など）、
免責事項などの定型文は全スコア計算前に除去します。

---

## 🗂 データソースについて(著作権上の配慮)

| データ | 出典 | 権利関係 |
|--------|------|----------|
| ir_summary | EDINET(金融庁)の有価証券報告書 | 法定開示情報。著作権法30条の4(情報解析目的の利用)の趣旨に合致 |
| press_release | 各企業公式IRページ(robots.txt確認済み) | 企業自身が広報目的で公開。取得前に必ずrobots.txtを確認 |

体験記サイト由来のデータは一切使用していません。サンプルデータ(`SAMPLE_DATA`)も
実在の投稿を転記したものではなく、決算の典型的なパターンをもとに作成した合成データです。

---

## 🗂 ファイル構成

```
companyGap/
├── collect.py        # EDINET API連携 + プレスリリース取得(robots.txt確認付き) + サンプル5社
├── companies.csv      # 実データ収集対象の実在企業10社(EDINETコード + プレスリリースURL)
├── engine.py          # 表現ギャップ計算コア(形態素解析 / TF-IDF / KW差分) + CLI表示
├── jobs.csv           # 収集したIR資料 & プレスリリースデータ
└── requirements.txt    # 依存パッケージ
```

対象10社: トヨタ自動車・本田技研工業・任天堂・野村総合研究所・日本電信電話・
三菱商事・日立製作所・キーエンス・ファーストリテイリング・ソフトバンク
(いずれも2026年7月時点で実在確認済みのIR資料URLを登録)

---

## 🛠 companies.csv の作り方(対象企業の追加・更新方法)

`companies.csv` の各行(`company,edinet_code,press_url`)は次の手順で用意しました。
企業を追加・差し替える場合も同じ手順で行えます。

### EDINETコードの調べ方

1. 金融庁が公開する公式のEDINETコードリストをダウンロード:
   https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip
2. 展開した `EdinetcodeDlInfo.csv`(cp932エンコーディング、全提出者の一覧)を
   正式社名で検索し、対応するEDINETコードを取得(例: トヨタ自動車 → E02144)

   ```bash
   python -c "
   import csv
   with open('EdinetcodeDlInfo.csv', encoding='cp932') as f:
       next(f)  # 1行目はメタ情報なので読み飛ばす
       for row in csv.DictReader(f):
           if 'トヨタ自動車' in row['提出者名']:
               print(row['ＥＤＩＮＥＴコード'], row['提出者名'])
   "
   ```
3. `python collect.py --edinet <コード>` を実行し、有価証券報告書が
   取得できることを確認

### プレスリリースURLの探し方

1. 「`<社名> IR 決算発表 プレスリリース 公式サイト`」等でWeb検索し、
   **企業公式ドメイン上**の決算関連リリース(HTMLまたはPDF)のURLを特定
2. 登録前に実際に取得できることを検証:

   ```bash
   python collect.py --edinet <コード> --press-url <URL>
   ```

   robots.txt の確認 → 取得 → テキスト抽出まで通ることを確認してから
   `companies.csv` に登録する(「実在確認済み」はこの検証を指す)
3. 決算関連URLは決算期ごとに変わるため、いずれ陳腐化します。
   その場合は行を削除せず、最新のリリースURLに更新してください

## 講義資料との対応(TF-IDFの式)

講義「検索対象の表現と索引付け」の定義
`w(t,d) = tf(t,d) × idf(t)`, `idf(t) = log(N/df(t)) + 1` に一致させるため、
全 TfidfVectorizer で `smooth_idf=False`・生のtf(sublinear_tfなし)を使用。
L2正規化(既定)は講義の「文書長による正規化」に相当する。

---

## ⚙️ EDINET APIキーの取得方法

1. https://disclosure2.edinet-fsa.go.jp/ にアクセスし利用者登録
2. メール認証後、マイページからAPIキーを発行
3. `export EDINET_API_KEY="発行されたキー"` を実行

APIキー未設定の場合は自動的にサンプルデータで動作します。

---

## 依存パッケージ

```
pandas
scikit-learn
requests
beautifulsoup4
pypdf
cryptography
fugashi
unidic-lite
```
