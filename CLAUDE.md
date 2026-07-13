# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit web app that measures the expression gap ("表現ギャップ") between a company's factual financial disclosure (EDINET 有価証券報告書) and the promotional language in its press releases, using TF-IDF cosine similarity, sentiment analysis, and keyword diffing. Japanese-language domain (all UI strings, sample data, and stopwords are in Japanese).

The project originally scraped internship-review sites (One Career, 就活会議) to compare stated company culture against intern experiences. That approach was dropped after reviewing those sites' terms of service (copyright attribution to members/operator, no-scraping clauses) — see the README's "データソースの倫理的検討" section. The current design instead compares EDINET-sourced factual disclosure text against company press releases, which is lower-risk (public statutory disclosure; 著作権法30条の4 rationale).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Generate sample data (20 companies, synthetic) into jobs.csv — required before running engine.py or app.py
python collect.py

# Fetch real data for one company (requires EDINET_API_KEY env var)
export EDINET_API_KEY="発行されたキー"
python collect.py --edinet <EDINETコード> [基準日 YYYY-MM-DD]

# CLI sanity check: prints a ranking table of all companies
python engine.py

# CLI detail view for one company (substring match on company name)
python engine.py A社

# Launch the web UI (must use `python -m streamlit`, not `streamlit run` directly)
python -m streamlit run app.py
```

There is no test suite, linter, or build step in this repo.

## Architecture

Three-file pipeline, no framework beyond Streamlit/pandas/scikit-learn:

- **`collect.py`** — produces `jobs.csv` (columns: `company`, `ir_summary`, `press_release`). Two modes:
  - Default: writes the hardcoded `SAMPLE_DATA` list (20 synthetic companies; only 5 base patterns exist — `_EXTRA_NAMES` companies 6–20 reuse one of the first 5 verbatim via `i % 5`, so they are not independent samples).
  - `--edinet <EDINETコード> [日付]`: calls the real EDINET API v2 (`fetch_document_list` / `find_yuho` / `search_yuho_recent`) to locate a company's 有価証券報告書 (docTypeCode 120), downloads it as CSV (`download_yuho_text`, type=5, UTF-16 tab-separated), and extracts specific XBRL text-block elements (`TARGET_ELEMENTS`: business policy/issues, business description), capped at 2000 chars. Requires `EDINET_API_KEY` env var; falls back to `SAMPLE_DATA` if the lookup or extraction fails. Verified end-to-end against the live API (Toyota, EDINET code E02144) — `TARGET_ELEMENTS` correctly matches real XBRL element names.
  - Press-release text (`fetch_press_release`) is fetched from a company's own IR page and is always gated by `can_fetch()` (robots.txt check) before any request; truncated to 1000 chars. Branches on the response's `Content-Type`: PDF (`pypdf`, needs the `cryptography` package too since many corporate IR PDFs are AES-encrypted for edit-protection) or HTML (BeautifulSoup, fed `res.content` — not `res.text` — so bs4 can sniff the real encoding; pages without a `charset` in their `Content-Type` header would otherwise get mis-decoded as Latin-1 by `requests`). Anything else logs a warning and returns `""`. Verified against real IR pages: EDINET/Toyota (XBRL), NRI (AES-encrypted PDF), Nintendo (charset-less HTML, was mojibake before the `res.content` fix).

- **`engine.py`** — all scoring logic; both `app.py` and the CLI import from here. Key entry points: `analyze_company(company, ir_summary, press_release) -> dict` and `analyze_all(csv_path) -> pd.DataFrame` (sorted ascending by `realness`, i.e. worst gap first).

  Tokenization (`tokenize()`) auto-selects a backend at import time via `_init_tagger()`, tried in order: **MeCab → fugashi → char n-gram fallback** (2–3 char substrings over Japanese Unicode ranges). This means `TfidfVectorizer` is configured differently depending on which mode is active (`analyzer="char_wb"` for chargram mode vs. a custom `tokenizer=tokenize` for MeCab/fugashi) — when touching TF-IDF logic, changes must work under both branches, and the current dev environment normally runs in chargram fallback mode since neither MeCab nor fugashi is installed by default.

  Sentiment (`sentiment_score()`) merges an optional `pn-ja.dic` (Tohoku University polarity dictionary, tab-separated `word\treading\tpos\tscore`, not checked into this repo) with the builtin `_BUILTIN_PN` dict in `engine.py`; builtin entries are overridden by `pn-ja.dic` on key collision. `_BUILTIN_PN` is scoped to IR/press-release phrasing (増益, 減損, 過去最高, 挑戦, 加速, etc.) — the old internship-review-domain entries (残業, やりがい, ストレス, etc.) have been removed. In chargram mode, sentiment is computed by substring search of the whole `_PN_DICT` against the raw text rather than through `tokenize()`. Sentiment is scored only against `press_release` (not `ir_summary`).

  The four metrics and how they compose:
  - `gap_score` (0–100, higher = more divergence): `1 − cosine_similarity` on TF-IDF vectors of `ir_summary` vs `press_release`.
  - `sentiment` (−1 to +1): mean polarity of matched dictionary words in `press_release`.
  - `kw_match` (0–100%): Jaccard overlap of each doc's top-20 TF-IDF keywords (`_top_keywords`, computed by splitting a single doc into pseudo-sentences to get a multi-document corpus for IDF).
  - `realness` (0–100, the headline score, "IR誠実度"): `realness_score()` = weighted blend, `(1 − gap/100)×0.5 + ((sentiment+1)/2)×0.3 + kw_match×0.2`, then ×100.

  `keyword_diff()` returns `company_only` (`ir_summary`-only), `intern_only` (`press_release`-only — name is a holdover, not a bug to "fix" casually since `analyze_company()` maps it to `kw_press`), and `common` keyword sets.

- **`app.py`** — Streamlit UI with three modes selected via sidebar radio: 全社ランキング (ranking of all companies via `analyze_all()`, cached with `@st.cache_data`), 企業詳細分析 (drill into one company from the CSV), 手動入力で分析 (paste arbitrary `ir_summary`/`press_release` text and call `analyze_company()` directly, bypassing the CSV). All three modes render `kw_ir`/`kw_press`/`kw_common` as colored pills and a representative sentence (`rep_ir`/`rep_press`) per side. UI copy is aligned with the IR/press-release domain throughout (no leftover internship-review wording); note the `kw-intern` CSS class name in the stylesheet is cosmetic and unrelated to that cleanup.

## Notes when modifying

- `jobs.csv` columns are `company`, `ir_summary`, `press_release` (not the old `company_page`/`intern_report`). It is listed in `.gitignore` and **not** tracked by git — regenerate it locally with `python collect.py` (sample data) or `python collect.py --edinet ...` (real data); don't assume a clean-checkout repo has it.
- `_STOPWORDS` in `engine.py` intentionally excludes generic terms like "当社", "会社", "企業", "当期", "前期", "事業" that appear in nearly every document and would otherwise dominate keyword extraction with no discriminative value — keep this in mind if scores look off after adding new sample companies.
- EDINET access requires `EDINET_API_KEY`; without it, `collect.py --edinet ...` prints an error and falls back to `SAMPLE_DATA`. `fetch_press_release()` is still gated by `robots.txt` via `can_fetch()` regardless of the EDINET path, and failures there are expected/best-effort, not bugs.
- `requirements.txt` includes `pypdf` and `cryptography` (for AES-encrypted PDF press releases) alongside the original pandas/scikit-learn/streamlit/requests/beautifulsoup4 set — don't drop these when trimming dependencies.
- Never hardcode a real `EDINET_API_KEY` value anywhere in this repo (docstrings, comments, sample commands) — use a placeholder like `"発行されたキー"`. One leaked into `collect.py`'s docstring once already; it wasn't committed, but treat any real key that touches this repo as compromised and reissue it via EDINET's API-key-reissue flow.
