# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A CLI tool that measures the expression gap ("表現ギャップ") between a company's factual financial disclosure (EDINET 有価証券報告書) and the promotional language in its press releases, using TF-IDF cosine similarity and keyword diffing. Japanese-language domain (all UI strings, sample data, and stopwords are in Japanese).

The project originally scraped internship-review sites (One Career, 就活会議) to compare stated company culture against intern experiences. That approach was dropped after reviewing those sites' terms of service — see the README's "データソースの倫理的検討" section. The current design instead compares EDINET-sourced factual disclosure text against company press releases (public statutory disclosure; 著作権法30条の4 rationale).

An earlier iteration also had a Streamlit web UI (app.py), a sentiment score (pn-ja.dic polarity dictionary), switchable keyword-extraction methods (tf / tfidf / textrank), and a word+char-n-gram blended gap similarity. These were removed to keep the deliverable at CLI scope with two metrics; the headline score now blends gap and keyword match only.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Generate sample data (5 companies, synthetic) into jobs.csv — required before running engine.py
python collect.py

# Fetch real data (requires EDINET_API_KEY env var; PowerShell: $env:EDINET_API_KEY="...")
export EDINET_API_KEY="発行されたキー"
python collect.py --edinet <EDINETコード>       # one company
python collect.py --batch companies.csv         # all 10 real companies

# Ranking of all companies
python engine.py

# Detail view for one company (substring match on company name)
python engine.py トヨタ
```

There is no test suite, linter, or build step in this repo.

## Architecture

Two-file pipeline (pandas / scikit-learn / requests / bs4):

- **`collect.py`** — produces `jobs.csv` (columns: `company`, `ir_summary`, `press_release`). Modes:
  - Default: writes the hardcoded `SAMPLE_DATA` list (5 synthetic companies, one per gap pattern, written at realistic 有報 length with partial vocabulary overlap between each company's IR and PR). Designed gap ordering: A・C・E (large) ≫ B・D (small). D社's press release deliberately ends with a disclaimer sentence to exercise `_strip_boilerplate`.
  - `--edinet <code>`: calls EDINET API v2 (`fetch_document_list` / `find_yuho` / `search_yuho_recent`) to locate the 有価証券報告書 (docTypeCode 120), downloads it as CSV (type=5, UTF-16 tab-separated), extracts XBRL text blocks (`TARGET_ELEMENTS`), capped at 2000 chars. Falls back to `SAMPLE_DATA` on failure.
  - `--batch companies.csv`: loops `collect_company` over the company list (columns: `company,edinet_code,press_url`), skipping failures. `fetch_document_list` caches per-date results (`_DOC_LIST_CACHE`) so batch runs don't re-scan the same dates per company.
  - `companies.csv` holds 10 real companies (トヨタ E02144, ホンダ E02166, 任天堂 E02367, NRI E05062, NTT E04430, 三菱商事 E02529, 日立 E01737, キーエンス E01967, ファーストリテイリング E03217, ソフトバンク E04426). Press-release URLs were verified live as of 2026-07 and will eventually go stale — refresh URLs rather than deleting rows.
  - Press-release text (`fetch_press_release`) is always gated by `can_fetch()` (robots.txt) before any request; truncated to 1000 chars. Branches on `Content-Type`: PDF (`pypdf` + `cryptography` for AES-encrypted corporate PDFs) or HTML (BeautifulSoup, fed `res.content` — not `res.text` — so bs4 sniffs the real encoding; charset-less pages would otherwise be mis-decoded as Latin-1).

- **`engine.py`** — all scoring logic plus the CLI entry point. Key entry points: `analyze_company(company, ir_summary, press_release) -> dict` and `analyze_all(csv_path) -> pd.DataFrame` (sorted ascending by `realness`, worst gap first).

  Tokenization (`tokenize()`) uses **fugashi (MeCab bindings) + UniDic (`unidic-lite`)** as a hard dependency — `engine.py` exits with an install hint if fugashi is missing. (Earlier versions auto-selected MeCab → fugashi → char n-gram; those branches were removed — the raw-MeCab path assumed IPAdic feature indices, which break with UniDic's quoted-CSV features, so fugashi's named feature access is the safe single backend. POS sets are UniDic-only: 接頭辞/接尾辞, 数詞, 非自立可能.) `tokenize()` parses whitespace-separated chunks (`_tokenize_chunk`), merges consecutive noun/prefix/suffix morphemes into compound nouns (営業/利益/率 → 営業利益率; a compound is only emitted if it contains at least one true 名詞), normalizes verbs/adjectives to base form, and drops numerals, pronouns, numeric+counter tokens, short Latin fragments, and light verbs (in `_STOPWORDS` as base forms). `_strip_boilerplate` removes disclaimer sentences before all scoring.

  All `TfidfVectorizer` instances use `smooth_idf=False` and raw tf (no `sublinear_tf`) to match the course formula `w(t,d)=tf×idf, idf=log(N/df)+1` (see comment above `calc_gap_score`). Keep new vectorizers consistent with this.

  The metrics:
  - `gap_score` (0–100, higher = more divergence): `1 − cosine` of `ir_summary` vs `press_release` TF-IDF vectors. The tokenizer is `_tokenize_split` (`split_compounds=True`), which emits each compound noun *plus* its constituent nouns so 海外向け販売/海外売上 partially match on 海外. Note `split_compounds` is used only here; keyword extraction uses plain `tokenize()`.
  - `kw_match` (0–100%): Jaccard overlap of each doc's top-20 TF-IDF keywords. `extract_keywords(text, n)` computes IDF over a background corpus of every `ir_summary`/`press_release` in `jobs.csv` (`_background_corpus()`, cached at module level) so cross-company terms sink automatically.
  - `realness` (0–100, headline "IR誠実度"): `realness_score()` = `(1 − gap/100)×0.7 + kw_match×0.3`, then ×100.

  `keyword_diff()` returns `company_only` (`ir_summary`-only), `intern_only` (`press_release`-only — name is a holdover; `analyze_company()` maps it to `kw_press`), and `common` lists, preserving importance order. `_most_representative_sentence()` uses LexRank-style centrality (TF-IDF sentence vectors → cosine matrix → PageRank).

## Notes when modifying

- `jobs.csv` columns are `company`, `ir_summary`, `press_release`. It is in `.gitignore` and not tracked — regenerate with `python collect.py` (sample) or `--batch companies.csv` (real data).
- `_STOPWORDS` intentionally excludes generic terms ("当社", "事業", …), light verbs as base forms, and counter words that appear in nearly every document. With corpus-level IDF most cross-company terms sink on their own; the stopword list still protects short documents.
- EDINET access requires `EDINET_API_KEY`; without it `collect.py` falls back to `SAMPLE_DATA`. `fetch_press_release()` failures are expected/best-effort, not bugs.
- Keep `pypdf` and `cryptography` in `requirements.txt` (AES-encrypted PDF press releases). `streamlit` was removed along with app.py — don't reintroduce it.
- Never hardcode a real `EDINET_API_KEY` value anywhere in this repo (docstrings, comments, sample commands) — use a placeholder like `"発行されたキー"`. Treat any real key that touches this repo as compromised and reissue it.
- Source files start with `# -*- coding: utf-8 -*-`; keep it (works around a phantom SyntaxError in some Python 3.10 environments with long multibyte comment lines).
