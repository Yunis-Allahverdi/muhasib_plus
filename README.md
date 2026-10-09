# HesabAI – auditable VAT reconciliation (1C ↔ e-taxes)

NeuroBridge Baku 2026 · AI Enterprise Solutions track

> **Outcome:** on a **real company month**, HesabAI gets **96.6%** of records right (VLOOKUP: 24.1%), with **0 false alarms, 0 missed discrepancies and 0 wrong pairings**. On a labelled synthetic test month (307 records), the Excel-style lookup accountants use today handles **23%** of records correctly. HesabAI handles **99.0%** with AI, using 4 AI requests, against **94.8%** with rules alone, when 1C comments are typed the way accountants really type them. **No discrepancy is missed**, and the rules alone make **0 wrong pairings** on all 10 test months. Every finding comes with evidence and a confidence score, and nothing is final until an accountant approves it.

## 1. The problem and the value

Every month an Azerbaijani accountant checks incoming e-invoices from **e-taxes.gov.az** against the purchases booked in **1C** before filing the VAT (ƏDV) return. The two sides rarely match cleanly:

- the same supplier is typed as `"BAKI ELEKTRİK ŞƏBƏKƏSİ" ASC`, `Baki Elektrik`, `BEŞ` or `Баку Электрик`;
- 1C document numbers are often internal (`ПТ-000123`), not the e-invoice number;
- one invoice is split across two 1C rows; amounts, VAT and VÖENs get mistyped; invoices are booked in the wrong month or twice.

Each miss costs money: VAT credit that is never claimed, credit that gets rejected, or credit claimed in the wrong period. Today this is done with VLOOKUP/SUMIF and by eye, which takes hours and fails exactly on the hard cases.

**What HesabAI gives the accountant:** upload both exports → every record is paired or flagged with one of 6 labels (amount/VAT mismatch, VÖEN mismatch, wrong period, missing in 1C, missing in e-taxes, duplicate in 1C). Each finding carries its evidence, a confidence score and its VAT impact, plus an Azerbaijani explanation and a draft supplier email. The accountant approves, rejects or escalates each finding. **HesabAI never posts or sends anything.**

On the synthetic test month (150 cases):

| | Value |
|---|---|
| Discrepancies found | 62 findings, **0 missed** |
| Input VAT in flagged records | 187,554 AZN (of 443,108 AZN) |
| Pairings the accountant must confirm (weak or AI evidence) | 17 |
| Estimated effort | ≈ 18 h manual vs ≈ 4 h reviewing HesabAI's evidence\* |

\* *Estimate from adjustable assumptions shown in the app (1.5 min per record and 10 min per issue manually; reviewing prepared evidence takes 30% of that). This is not a measured customer result. The synthetic month has a deliberately high error rate.*

## 2. Prototype and what the AI contributes

```
1C + e-taxes ──► duplicates ──► rules (invoice no + name/VÖEN) ──► fuzzy (translit, amount, date, splits)
                                                                         │ leftovers only (~10%)
                                                                         ▼
                                      AI: pick the right 1C row(s) from ≤6 candidates + reason + confidence
                                                                         │
             labels (amount / VÖEN / period) ◄── every pairing ──────────┘
                     │
                     ▼
     review queue: evidence + confidence ──► accountant approves / rejects / escalates (timestamped)
                     │
                     └─► on request: AI explanation + supplier email draft (Azerbaijani, editable, never sent)
```

1. **Duplicates**: same supplier, document number and amount booked twice in 1C.
2. **Rules**: normalised invoice number plus agreement on supplier name or VÖEN. Handles `MT 2601 123456`, `mt2601123456`, last-6-digits.
3. **Fuzzy**: Azerbaijani/Cyrillic transliteration and legal-form stripping, then name match + same amount + closest date. A split invoice is accepted only when exactly one pair of rows adds up to the total.
4. **Weak evidence (always sent to review)**: exact amount + close date + a shortened name (`Baki Elektrik`) or the same goods text. It is used only when the pair is the single candidate in both directions; ambiguous cases are flagged, not guessed.
5. **AI (LLM)**, only for what is left (14 of 144 invoices on the easy month, 19 on the realistic one), **batched 5 invoices per request**, so a whole month needs 3–4 requests. It gets each invoice with at most 6 candidate 1C rows and returns the match, a reason in Azerbaijani and a confidence. This is where meaning matters: `Caspian Office Supply` = `Xəzər Ofis Təchizatı`, `Кавказ Химия` = `Qafqaz Kimya`, combined with a wrong amount that defeats every rule.
6. **Labelling**: amount/VAT, VÖEN and period checks on every pairing, whoever made it.

**Guardrails on the AI** (all covered by tests in `tests/test_engine.py`):

- below the confidence threshold (default 0.6) → no pairing, the record goes to review;
- above the threshold → paired, but still **flagged for the accountant to confirm**;
- answers naming a record that was not among the candidates, or malformed JSON → ignored;
- AI outage, rate limit or used-up quota → the record is flagged for review; the run never crashes or guesses;
- a 1C row quoting a **different e-invoice number** is never offered to the AI. Our first Gemini run showed why: the AI paired same-supplier, same-goods records whose amounts differed 3–4×. That failure became the `doc_conflict` guard and a regression test.

**AI vs no AI** (same data, `python evaluate.py data` / `data_realistic`):

<!-- HYBRID_RESULTS -->
Same test month (seed 42, 307 records), AI = Groq `openai/gpt-oss-120b` (free tier), measured:

| Metric | Exact | Rules + fuzzy | **Hybrid (rules + AI)** |
|---|---|---|---|
| **Easy comments**: record accuracy | 23.1% | 98.7% | **100%** |
| amount mismatches correctly paired | 6/28 | 24/28 | **28/28** |
| wrong pairings / false alarms / missed | 5 / 186 / 0 | 0 / 0 / 0 | **0 / 0 / 0** |
| AI requests (14 invoices, 5 per request) | – | – | 3 |
| **Realistic comments**: record accuracy | 23.1% | 94.8% | **99.0%** |
| alias-name invoices / splits correct | 0/62 / 3/45 | 56/62 / 39/45 | **62/62 / 45/45** |
| false alarms / missed | 186 / 0 | 12 / 0 | **0 / 0** |
| wrong pairings (all flagged for review) | 5 | 0 | 2 |
| AI requests (19 invoices, 5 per request) | – | – | 4 |

**What the AI adds**: it resolves what no rule can, for example a translated supplier name with an internal 1C number and a mistyped amount. On realistic data it removes all 12 false alarms and fixes every alias case and split.
**What it still gets wrong**: 1 pairing on the realistic month. A 1C row that really belongs to invoice P0136 (net mistyped as 1,852.43 instead of 852.43) was given to another invoice from the same supplier. It is labelled AMOUNT_MISMATCH and flagged for review, so the accountant sees it.

**Two AI failures we found and fixed with deterministic guards** (each has a regression test):
1. *First Gemini run*: the AI paired same-supplier records although the 1C row quoted a **different e-invoice number** → such rows are no longer offered to the AI (`doc_conflict`).
2. *First Groq run (4 wrong pairings)*: the AI gave the two halves of one split invoice to two other invoices → when two free 1C rows add up exactly to an invoice, the AI is told so and those rows are **reserved** for it (`exact_split`). Realistic accuracy went 98.4% → 99.0%, and wrong pairings 4 → 2.

An earlier unbatched run with Gemini (`gemini-3.6-flash`) on the easy month reached 99.3% with 0 wrong pairings, before its free daily quota ran out.
<!-- /HYBRID_RESULTS -->

## 3. Quality testing

**Comparison with the current approach.** The baseline is what an accountant does in Excel: VLOOKUP on the invoice number.

Test month, seed 42, 307 records (`results/`, `results_realistic/`):

| Metric | Exact (VLOOKUP) | Rules + fuzzy, easy comments | Rules + fuzzy, realistic comments |
|---|---|---|---|
| Record accuracy | 23.1% | **98.7%** | **94.8%** |
| False alarms | 186 | 0 | 12 |
| Missed discrepancies | 0 | 0 | 0 |
| Pairing accuracy | 17.2% | 98.6% | 94.3% |
| Wrong pairings (the dangerous error) | 5 | **0** | **0** |

**Robustness: 10 different generated months** (`python evaluate_seeds.py`, saved to `results/seeds_summary.csv`):

| Data | Method | Accuracy mean [min–max] | False alarms (mean) | Missed (max) | Wrong pairings (max) |
|---|---|---|---|---|---|
| easy | exact | 25.0% [18.6–29.7] | 166.7 | 0 | 7 |
| easy | rules + fuzzy | **98.7%** [97.3–100] | 0.0 | 0 | 0 |
| realistic | exact | 25.0% [18.6–29.7] | 166.7 | 0 | 7 |
| realistic | rules + fuzzy | **92.7%** [87.7–94.8] | 16.6 | 0 | 0 |

**How the test data is built** (`generate_data.py`, fully synthetic). 9 case types with injected errors: clean, clean with alias name + internal 1C number, split, amount/VAT error (digit swap, wrong VAT, net typo), wrong VÖEN, missing in 1C, missing in e-taxes, wrong period, duplicate. There are also two **decoy suppliers** with confusable names (`Azər Tikinti` vs `Azər Tikinti Materialları`, `Xəzər Ofis Təchizatı` vs `Xəzər Ofis Mebel`).
`--realistic` keeps exactly the same cases but types the 1C comment like a real accountant: blank 25%, generic 30% (`Mal alışı`, `Поступление товаров`), first word only 30%, full text 15%. **That run is the honest one.** In the easy run the comment repeats the e-invoice goods text, which flatters any method that reads it.

**Automated tests**: `python -m pytest -q` runs 51 tests in about 5 s, with no network:

- normalisation (Cyrillic, Azerbaijani letters, legal forms), amount parsing (`1 234,56`), input validation;
- every label, splits, ambiguous splits, duplicates, decoys, the weak-evidence review rule;
- AI guardrails: low confidence, invented IDs, junk answers, outage, AI not called when the rules are sure, the doc-conflict guard;
- quota protection: batching, two invoices claiming the same 1C row, an invoice skipped in a batch answer, the call budget, merge-safe cache;
- end-to-end regression on 3 seeds × easy/realistic: **0 wrong pairings, 0 missed discrepancies**, plus an accuracy floor.

**Failures, honestly.** Every failed record per method is written to `results*/failures.csv` and shown in the app. The remaining rule failures are amount errors on records that have *both* an alias name and an internal 1C number, which is the AI's job. On the realistic data, some generic or blank comments leave a correct pairing unconfirmed, and both records are then reported as missing.

**Real month: independent test, not tuned on.** A real September purchase month from an Azerbaijani company (28 e-invoices, 30 1C rows, 58 records). It was labelled by hand with a written reason per record, and checked against the accountant's own labels with 100% agreement. Each method was run once on it after the engine was finished; nothing was adjusted to fit it. The data stays private (`data_real/` is in `.gitignore`).

| Real month | Exact (VLOOKUP) | Rules + fuzzy | **Hybrid (rules + AI)** |
|---|---|---|---|
| Record accuracy | 24.1% | 70.7% | **96.6%** |
| False alarms | 30 | 9 | **0** |
| Missed discrepancies | 0 | 0 | **0** |
| Wrong pairings | 0 | 0 | **0** |
| Alias names / splits / wrong period correct | 0/10 · 0/6 · 0/4 | 4/10 · 3/6 · 2/4 | **10/10 · 6/6 · 4/4** |
| AI requests (11 invoices) | – | – | 3 ($0, Groq free tier) |

Real data is much harder for the rules than our synthetic month (70.7% vs 94.8%). Suppliers appear as abbreviations (`BMA`), English (`Nasimi Print`, `Khazri Paper`), Cyrillic (`ФЛ Гусейнли Р.Т.`, `Шемахы Даш`) or split under a nickname. This is exactly where the AI step earns its place. The only miss: an English-named supplier with a mistyped amount, where the AI was not confident enough. Both records went to review instead of being guessed.

## 4. Feasibility

**Data needed**: two standard exports, CSV or Excel, nothing else.

| e-taxes (incoming e-invoices) | 1C (purchase documents) |
|---|---|
| `portal_id, seller_name, seller_voen, invoice_no, invoice_date, net_amount, vat_amount, item_description` | `onec_id, counterparty, voen, doc_no, doc_date, net_amount, vat_amount, comment` |

Uploads are checked for missing columns, dates and amounts (both `1234.56` and `1 234,56` work), with a readable error message. No training data is needed, and no client data leaves the machine except the ≤6-candidate snippets sent to the LLM for the leftover records.

**Running cost** (measured per uncertain invoice: up to ~550 input and ~350 output tokens, including the model's reasoning; about 10–13% of invoices need the AI, 5 per request):

| Firm size | AI work per month | Groq / Gemini (free tier) | Claude Haiku 5.5 ($0.10/$0.50 per M) | Claude Sonnet 5.5 ($2/$10 per M) |
|---|---|---|---|---|
| 500 invoices | ~50 invoices → ~10 requests | $0 | ≈ $0.01 | ≈ $0.23 |
| 2,000 invoices | ~200 → ~40 requests | $0 (Groq / Gemini free tier) | ≈ $0.05 | ≈ $0.92 |
| 20,000 invoices (accounting firm) | ~2,000 → ~400 requests | paid tier needed | ≈ $0.46 | ≈ $9.20 |

Claude figures exclude thinking tokens, which can add a multiple of the output cost. The rules handle 300 records in under 0.1 s. AI answers are cached (`llm_cache.json`), so re-running a month costs nothing. Hosting is a single Streamlit process.

**Next step: a 4-week pilot with one Baku accounting firm.**

1. Map their real 1C and e-taxes export columns.
2. Run one closed month in parallel with their manual check.
3. Measure hours spent, discrepancies found by each side, and false alarms.
4. Tune thresholds on that month and freeze them.
5. Re-measure on the next month.

Success criterion: no discrepancy missed that the manual check found, and at least 50% less review time.

## 5. What is different

- **AI is used only where it adds information**, on the uncertain ~10% of records, never as a black box over the whole file. The rules are cheaper, faster and explainable, so they go first. The AI is measured against them on the same data.
- **Evidence first, human last.** Every pairing says *why* (name similarity, matching invoice number, goods text, the AI's reason). Weak and AI pairings must be confirmed. Decisions are timestamped per finding, and nothing is posted or sent automatically.
- **Built for Azerbaijan.** Azerbaijani/Cyrillic/English name forms, VÖEN checks, e-taxes invoice-number formats, and Azerbaijani explanations and supplier emails.
- **Measured honestly.** A VLOOKUP baseline, a deliberately harder "realistic" run, 10 seeds, a published failure list, and an AI failure we found and turned into a guard.

## Run

```bash
pip install -r requirements.txt
# AI key: open .env (next to app.py) and paste a free Groq key after OPENAI_API_KEY=
#   (or GEMINI_API_KEY / ANTHROPIC_API_KEY; only one provider should be active)
python test_key.py                                        # checks the key works
python generate_data.py 42 150 data                       # labelled test month
python generate_data.py 42 150 data_realistic --realistic # same month, realistic 1C comments
python generate_data.py 7 40 data_demo                    # smaller demo month
python evaluate.py data                                   # exact vs rules vs hybrid -> results/
python evaluate.py data_realistic --out results_realistic
python evaluate_seeds.py                                  # 10 months, no AI -> results/seeds_summary.csv
python -m pytest -q                                       # 51 offline tests (no AI calls)
streamlit run app.py
```

Add `--no-llm` to `evaluate.py` to run only the two non-AI methods.
**Quota protection** (set in `.env`): `HESAB_LLM_BATCH` = invoices per AI request (default 5), and `HESAB_MAX_LLM_CALLS` = hard stop on real requests per run (default 100). Answers are cached and shared safely between the app and `evaluate.py`. Any OpenAI-compatible service works with `OPENAI_BASE_URL` (Groq is preset; the model is picked automatically or set with `HESAB_OPENAI_MODEL`). If a Gemini model's daily free quota runs out, the app switches to the next flash model. Set `HESAB_GEMINI_MODEL=...` in `.env` to pin one. In VS Code: Ctrl+Shift+B starts the app with auto-reload, and F5 runs it under the debugger.

## Limitations

- Data is synthetic. Real 1C export layouts and real error frequencies must be validated in the pilot.
- One error per case in the test set; real records can have several at once.
- Time-saving figures are assumption-based estimates, not measurements.
- The LLM can still pair wrongly within its candidate set. That is why AI pairings always need confirmation and every pairing shows its evidence.
- Free tiers (Groq, Gemini) are rate-limited, and Gemini's daily quota is small. A production pilot needs a paid tier or Claude Haiku/Sonnet.
- The AI results come from one test month and one model; repeating them across seeds costs AI requests and is the next validation step.

## Disclosure

- Models: Groq `openai/gpt-oss-120b` (used for the reported AI results; any OpenAI-compatible service via `OPENAI_BASE_URL`), Gemini flash (Google, picked automatically or via `HESAB_GEMINI_MODEL`), Claude (Anthropic API, default `claude-sonnet-5-5`, via `HESAB_CLAUDE_MODEL`) or GPT (OpenAI API, default `gpt-4.1-mini`, via `HESAB_OPENAI_MODEL`).
- Libraries: Python, pandas, rapidfuzz, streamlit, openpyxl, google-genai, anthropic, openai, pytest.
- Data: fully synthetic, generated by `generate_data.py`. No real company or client data.
- Built during the hackathon (9 Oct 2026) with help from AI coding assistants.
