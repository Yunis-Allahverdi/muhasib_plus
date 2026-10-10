# MÜHASİB+ - demo app.  Run:  python -m streamlit run app.py
import html
import io
import json
import os

import altair as alt
import pandas as pd
import streamlit as st

import engine
import llm

st.set_page_config(page_title="MÜHASİB+ - VAT reconciliation", layout="wide")

# ---------------- look & feel (brand colours from the logo: navy / teal / green) ----------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root { --navy:#111A33; --teal:#0E9F8E; --teal-dark:#0B7C8C; --green:#10B981; --cyan:#22D3EE; --line:#D6E7E8; }
.block-container { padding-top: 1.6rem; max-width: 1500px; }
[data-testid="stHeader"] { background: transparent; }

/* hero banner */
.mh-hero { background: linear-gradient(120deg, #111A33 0%, #0B4F6C 45%, #0E9F8E 80%, #10B981 100%);
  border-radius: 18px; padding: 26px 32px; color: #fff; margin-bottom: 18px;
  box-shadow: 0 10px 30px rgba(14,159,142,.18); position: relative; overflow: hidden; }
.mh-hero:after { content:""; position:absolute; right:-60px; top:-60px; width:260px; height:260px; border-radius:50%;
  background: radial-gradient(circle, rgba(34,211,238,.35), rgba(34,211,238,0) 70%); }
.mh-hero .eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: .72rem; font-weight: 700; opacity: .85; }
.mh-hero h1 { color: #fff !important; font-size: 1.9rem; margin: .25rem 0 .35rem 0; padding: 0; font-weight: 800; }
.mh-hero p { margin: 0; opacity: .9; font-size: .95rem; max-width: 900px; }
.mh-hero .chips { margin-top: 12px; display:flex; gap:8px; flex-wrap:wrap; }
.mh-hero .chip { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.25); border-radius: 999px;
  padding: 3px 12px; font-size: .78rem; font-weight: 600; }

/* KPI cards */
[data-testid="stMetric"] { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px 12px;
  box-shadow: 0 2px 10px rgba(17,26,51,.05); border-top: 4px solid var(--teal); }
[data-testid="stMetricLabel"] * { font-size: .78rem !important; font-weight: 600; color: #4B5B73;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
[data-testid="stMetricValue"] { color: var(--navy); font-weight: 800; }
[data-testid="stMetricValue"] * { font-size: 1.85rem !important; }

/* tabs as pills */
.stTabs [role="tablist"] { gap: 6px; background: #E3F2F1; padding: 6px; border-radius: 14px; border: none; width: fit-content; }
.stTabs [data-testid="stTab"] { border-radius: 10px; padding: 8px 18px !important; font-weight: 600; color: #35506B; }
.stTabs [data-testid="stTab"]:hover { background: rgba(14,159,142,.10); }
.stTabs [data-testid="stTab"][aria-selected="true"] { background: linear-gradient(120deg, #0B7C8C, #0E9F8E 60%, #10B981);
  box-shadow: 0 4px 12px rgba(14,159,142,.28); }
.stTabs [data-testid="stTab"][aria-selected="true"] * { color: #fff !important; }

/* buttons */
.stButton > button, .stDownloadButton > button { font-weight: 600; border-radius: 10px; transition: all .15s ease; }
[data-testid="stBaseButton-primary"] { background: linear-gradient(120deg, #0B7C8C, #0E9F8E 55%, #10B981); border: none; }
[data-testid="stBaseButton-primary"]:hover { filter: brightness(1.07); box-shadow: 0 6px 16px rgba(14,159,142,.3); }
[data-testid="stBaseButton-secondary"]:hover { border-color: var(--teal); color: var(--teal-dark); }

/* tables, sidebar, headings */
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #F2FAF9 0%, #E3F2F1 100%); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] img { border-radius: 12px; }
h2, h3 { color: var(--navy); }
h3 { font-size: 1.3rem !important; border-left: 4px solid var(--teal); padding: 2px 0 2px 10px !important; margin-top: .6rem; }

/* evidence card */
.mh-card { background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 18px; margin: 6px 0 12px; }
.mh-card ul { margin: 0; padding-left: 1.1rem; } .mh-card li { margin: 3px 0; }
.mh-pill { display:inline-block; border-radius:999px; padding:2px 10px; font-size:.78rem; font-weight:700; margin-right:6px; }
.mh-foot { color:#6B7A90; font-size:.78rem; text-align:center; margin-top:28px; }
</style>
""", unsafe_allow_html=True)


def hero(title, text, chips=()):
    chips_html = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)
    st.markdown(f'<div class="mh-hero"><div class="eyebrow">MÜHASİB+ · ƏDV üzləşdirməsi · 1C ↔ e-taxes</div>'
                f'<h1>{html.escape(title)}</h1><p>{html.escape(text)}</p>'
                f'<div class="chips">{chips_html}</div></div>', unsafe_allow_html=True)


# status colours used in every table (background, text)
STATUS_STYLE = {
    "OK": ("#DCFCE7", "#166534"),
    "Amount / VAT mismatch": ("#FEF3C7", "#92400E"),
    "VÖEN (tax ID) mismatch": ("#FEE2E2", "#991B1B"),
    "Booked in wrong period": ("#E0E7FF", "#3730A3"),
    "In e-taxes, missing in 1C": ("#FFEDD5", "#9A3412"),
    "In 1C, no e-invoice in e-taxes": ("#FCE7F3", "#9D174D"),
    "Duplicate in 1C": ("#EDE9FE", "#5B21B6"),
}


def style_table(view):
    def status_css(v):
        bg, fg = STATUS_STYLE.get(v, ("", ""))
        return f"background-color:{bg};color:{fg};font-weight:600" if bg else ""
    sty = view.style.map(status_css, subset=["status"])
    if "review" in view.columns:
        sty = sty.map(lambda v: "color:#B45309;font-weight:700" if v else "", subset=["review"])
    nums = {c: "{:,.2f}" for c in ["net e-taxes", "net 1C"] if c in view.columns}
    return sty.format(nums, na_rep="")

LABEL_TEXT = {
    "OK": "OK",
    "AMOUNT_MISMATCH": "Amount / VAT mismatch",
    "VOEN_MISMATCH": "VÖEN (tax ID) mismatch",
    "PERIOD_MISMATCH": "Booked in wrong period",
    "MISSING_IN_1C": "In e-taxes, missing in 1C",
    "MISSING_IN_PORTAL": "In 1C, no e-invoice in e-taxes",
    "DUPLICATE_IN_1C": "Duplicate in 1C",
}
IMPACT = {
    "AMOUNT_MISMATCH": "VAT credit may be over- or under-claimed",
    "VOEN_MISMATCH": "VAT credit may be rejected for wrong supplier ID",
    "PERIOD_MISMATCH": "VAT credit claimed in the wrong month",
    "MISSING_IN_1C": "VAT credit not claimed (money left on the table)",
    "MISSING_IN_PORTAL": "VAT not deductible without an e-invoice",
    "DUPLICATE_IN_1C": "Same purchase booked twice",
}


def read_any(f, cols, side):
    if f.name.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(f, dtype=str)
    else:
        df = pd.read_csv(f, dtype=str, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    return engine.prepare(df.fillna("").to_dict("records"), cols, side)


# ---------------- sidebar ----------------
st.sidebar.image(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_wide.png"), width="stretch")
st.sidebar.caption("Auditable VAT reconciliation: 1C ↔ e-taxes. Synthetic demo data.")
src = st.sidebar.radio("Data", ["Demo month (synthetic)", "Upload files"])
if src == "Upload files":
    fp = st.sidebar.file_uploader("e-taxes incoming e-invoices (CSV/XLSX)", type=["csv", "xlsx"])
    fc = st.sidebar.file_uploader("1C purchase documents (CSV/XLSX)", type=["csv", "xlsx"])
    if not (fp and fc):
        st.info("Upload both files, or switch to the demo month.")
        st.stop()
    try:
        portal = read_any(fp, engine.PORTAL_COLS, "e-taxes file")
        onec = read_any(fc, engine.ONEC_COLS, "1C file")
    except ValueError as e:
        st.error(f"Cannot read the uploaded files: {e}")
        st.caption(f"Required columns – e-taxes: {', '.join(engine.PORTAL_COLS)}; 1C: {', '.join(engine.ONEC_COLS)}")
        st.stop()
else:
    d = "data_demo" if os.path.exists("data_demo/portal.csv") else "data"
    portal, onec = engine.load_csv(f"{d}/portal.csv"), engine.load_csv(f"{d}/onec.csv")

method = st.sidebar.selectbox("Method", ["Hybrid (rules + fuzzy + AI)", "Rules + fuzzy (no AI)", "Exact match (VLOOKUP baseline)"])
min_conf = 0.6
min_per_record = 1.5
min_per_issue = 10.0
if llm.provider() is not None:
    st.sidebar.success(f"AI provider: {llm.provider()}")
    st.sidebar.caption(f"Quota protection: {os.environ.get('HESAB_LLM_BATCH') or 5} invoices per AI request, "
                       f"max {llm.MAX_CALLS or '∞'} requests per app start; answers are cached. "
                       f"Used so far: {llm.stats['calls']} requests, {llm.stats['cached']} from cache.")
    if st.sidebar.button("Test AI connection"):
        try:
            ans = llm.ask_json('Return only JSON: {"ok": true}')
            if ans.get("ok"):
                st.sidebar.success(f"AI works (model {llm.model_name()})")
            else:
                st.sidebar.error("AI replied but not with the expected JSON")
        except Exception as e:
            st.sidebar.error(f"AI call failed: {e}")


@st.cache_data(show_spinner=False)
def run(method, portal_json, onec_json, min_conf, ai_provider):
    # ai_provider is part of the cache key, so adding a key re-runs instead of reusing a no-AI result
    portal, onec = json.loads(portal_json), json.loads(onec_json)
    errors = []
    if method.startswith("Exact"):
        return engine.run_exact(portal, onec), errors
    if method.startswith("Rules"):
        return engine.run_fuzzy(portal, onec), errors
    # engine.run_hybrid catches AI errors itself and flags those records for review
    log = lambda msg: errors.append(msg.strip()) if "LLM failed" in msg else None
    return engine.run_hybrid(portal, onec, llm.ask_json, min_conf=min_conf, log=log), errors


with st.spinner("Reconciling... (the AI step can take a minute on the Gemini free tier)"):
    res, ai_errors = run(method, json.dumps(portal), json.dumps(onec), min_conf, llm.provider())
if ai_errors:
    run.clear()  # do not keep a failed AI run in the cache; next rerun tries again
    st.warning(f"AI failed on {len(ai_errors)} record(s), which are flagged for review instead. "
               f"First error: {ai_errors[0]}")

P = {p["portal_id"]: p for p in portal}
C = {c["onec_id"]: c for c in onec}
if "decisions" not in st.session_state:
    st.session_state.decisions = {}  # finding key -> (decision, timestamp)


def fkey(rid, f):
    # a decision belongs to one finding: same record, same label, same partners
    return f"{rid}|{f['label']}|{';'.join(sorted(f['partners']))}"

# one row per issue (portal-side for paired issues, plus 1C-only issues)
rows = []
seen = set()
for rid, f in res.items():
    if rid in seen:
        continue
    group = [rid] + f["partners"] if f["label"] != "DUPLICATE_IN_1C" else [rid]
    seen.update(group)
    pids = [x for x in group if x.startswith("P")]
    cids = [x for x in group if x.startswith("C")]
    p = P.get(pids[0]) if pids else None
    review = any(res[x].get("needs_review") for x in group if x in res)
    dec, dec_at = st.session_state.decisions.get(fkey(rid, f), ("pending" if f["label"] != "OK" or review else "", ""))
    rows.append({
        "id": rid, "status": LABEL_TEXT[f["label"]], "label": f["label"],
        "supplier (e-taxes)": p["seller_name"] if p else "",
        "supplier (1C)": ", ".join(C[x]["counterparty"] for x in cids) if cids else "",
        "invoice": p["invoice_no"] if p else "", "1C doc": ", ".join(C[x]["doc_no"] for x in cids),
        "net e-taxes": p["net"] if p else None, "net 1C": round(sum(C[x]["net"] for x in cids), 2) if cids else None,
        "matched by": f["how"], "confidence": round(f["confidence"], 2),
        "review": "⚠ needs review" if review else "",
        "decision": dec, "decided at": dec_at,
        "_pids": pids, "_cids": cids, "_evidence": f["evidence"], "_key": fkey(rid, f),
    })
df = pd.DataFrame(rows)
to_check = df[(df.label != "OK") | (df.review != "")]  # issues + weak/AI pairings the accountant must confirm

hero("September 2026 – VAT reconciliation",
     "Every e-invoice from e-taxes.gov.az is matched to 1C with evidence and a confidence score. "
     "AI is used only for the uncertain records, and nothing is posted or sent without the accountant's decision.",
     chips=[f"Method: {method.split(' (')[0]}", f"{len(portal)} e-invoices · {len(onec)} 1C documents",
            f"AI: {llm.provider() or 'off (cached only)'}"])

tab1, tab2, tab3 = st.tabs([":material/table_chart: Reconciliation", ":material/manage_search: Issue detail + AI explanation",
                            ":material/verified: Evaluation (proof)"])

with tab1:
    issues = df[df.label != "OK"]
    k = st.columns(6)
    k[0].metric("e-taxes invoices", len(portal))
    k[1].metric("1C documents", len(onec))
    k[2].metric("Reconciled OK", int(((df.label == "OK") & (df.review == "")).sum()))
    k[3].metric("Issues to review", len(issues))
    k[5].metric("Pairings to confirm", int(((df.label == "OK") & (df.review != "")).sum()),
                help="Weak-evidence or AI-proposed pairings the accountant must confirm")
    vat_at_risk = sum(P[r["_pids"][0]]["vat"] for _, r in issues.iterrows() if r["_pids"]) + \
        sum(C[x]["vat"] for _, r in issues.iterrows() if not r["_pids"] for x in r["_cids"])
    k[4].metric("VAT flagged, AZN", f"{vat_at_risk:,.0f}", help=f"Input VAT in flagged records: {vat_at_risk:,.2f} AZN")
    manual = (len(portal) + len(onec)) * min_per_record + len(issues) * min_per_issue
    tool = len(issues) * min_per_issue * 0.3
    st.caption(f"Estimated manual effort ≈ {manual / 60:.1f} h vs ≈ {tool / 60:.1f} h reviewing MÜHASİB+'s evidence "
               f"(assumptions in sidebar; estimate, not a measured customer result).")

    st.subheader("Issues by type")
    counts = issues["status"].value_counts().rename_axis("status").reset_index(name="findings")
    if not counts.empty:
        chart = alt.Chart(counts).mark_bar(cornerRadiusEnd=6, height=22).encode(
            y=alt.Y("status:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320, labelFontSize=13)),
            x=alt.X("findings:Q", title="findings", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("findings:Q", legend=None, scale=alt.Scale(range=["#22D3EE", "#0E9F8E", "#0B5E6B"])),
            tooltip=["status", "findings"])
        labels = chart.mark_text(align="left", dx=6, fontWeight="bold", color="#111A33").encode(text="findings:Q")
        st.altair_chart((chart + labels).properties(height=44 * len(counts) + 20, padding={"left": 16, "right": 16})
                        .configure_view(stroke=None), width="stretch")

    st.subheader("Findings")
    f1, f2 = st.columns([4, 1.4])
    show = f1.multiselect("Show", list(LABEL_TEXT.values()), default=[v for v in LABEL_TEXT.values() if v != "OK"])
    only_review = f2.checkbox("Include pairings to confirm", value=True,
                              help="Also show OK pairings that rest on weak or AI evidence and need confirmation")
    mask = df.status.isin(show) | (only_review & (df.review != ""))
    view = df[mask].drop(columns=["label", "_pids", "_cids", "_evidence", "_key"])
    st.dataframe(style_table(view), width="stretch", hide_index=True, height=420,
                 column_config={"confidence": st.column_config.ProgressColumn("confidence", min_value=0, max_value=1,
                                                                              format="%.2f")})

    out = df.drop(columns=["_pids", "_cids", "_key"]).copy()
    out["evidence"] = out.pop("_evidence").apply(lambda e: " | ".join(e))
    buf = io.BytesIO()
    out.to_excel(buf, index=False)
    st.download_button("Download reconciliation report (.xlsx)", buf.getvalue(), "hesabai_report.xlsx",
                       type="primary", icon=":material/download:")

with tab2:
    if to_check.empty:
        st.success("No issues.")
    else:
        pending_only = st.checkbox("Only pending decisions", value=False)
        pool = to_check[to_check.decision == "pending"] if pending_only else to_check
        if pool.empty:
            st.success("All findings have a decision.")
            pool = to_check
        pick = st.selectbox(f"Finding ({len(pool)})", pool.index, format_func=lambda i: f"{df.at[i, 'id']} – {df.at[i, 'status']}{' ⚠' if df.at[i, 'review'] else ''} – {df.at[i, 'supplier (e-taxes)'] or df.at[i, 'supplier (1C)']} – {df.at[i, 'decision']}")
        r = df.loc[pick]
        bg, fg = STATUS_STYLE.get(r["status"], ("#E8F4F3", "#111A33"))
        st.markdown(f'<span class="mh-pill" style="background:{bg};color:{fg}">{html.escape(r["status"])}</span>'
                    f'<span class="mh-pill" style="background:#E8F4F3;color:#0B7C8C">{html.escape(r["matched by"])}'
                    f' · confidence {r["confidence"]:.2f}</span>'
                    f'<span class="mh-pill" style="background:#F1F5F9;color:#334155">decision: {html.escape(r["decision"] or "–")}</span>',
                    unsafe_allow_html=True)
        st.subheader(r["status"])
        if r["review"]:
            st.warning("Weak or AI-proposed pairing – confirm the 1C ↔ e-taxes link before relying on it.",
                       icon=":material/warning:")
        why = IMPACT.get(r["label"], "Pairing is not certain; a wrong link would hide a real discrepancy.")
        items = "".join(f"<li>{html.escape(e)}</li>" for e in r["_evidence"]) or "<li>–</li>"
        st.markdown(f'<div class="mh-card"><b>Why it matters:</b> {html.escape(why)}'
                    f'<div style="margin-top:8px"><b>Evidence</b></div><ul>{items}</ul></div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        a.write("**e-taxes record**")
        def record_table(recs):
            t = pd.DataFrame(recs).drop(columns=["net", "vat"], errors="ignore").T
            t.columns = ["value"] if len(recs) == 1 else [f"row {i + 1}" for i in range(len(recs))]
            return t
        a.dataframe(record_table([P[x] for x in r["_pids"]]) if r["_pids"] else pd.DataFrame(), width="stretch")
        b.write("**1C record(s)**")
        b.dataframe(record_table([C[x] for x in r["_cids"]]) if r["_cids"] else pd.DataFrame(), width="stretch")

        if st.button("Generate AI explanation + supplier email (Azerbaijani)", icon=":material/auto_awesome:"):
            ptxt = engine.fmt_p(P[r["_pids"][0]]) if r["_pids"] else ""
            ctxt = "; ".join(engine.fmt_c(C[x]) for x in r["_cids"])
            try:
                st.session_state["exp_" + r["id"]] = llm.explain(r["label"], r["_evidence"], ptxt, ctxt)
            except Exception as e:
                st.error(f"AI unavailable: {e}")
        ex = st.session_state.get("exp_" + r["id"])
        if ex:
            st.info(ex.get("explanation", ""))
            st.text_input("Email subject", ex.get("email_subject", ""))
            st.text_area("Email draft (edit before sending)", ex.get("email_body", ""), height=200)

        st.subheader("Accountant decision")
        st.caption("Nothing is sent or posted without it.")
        c1, c2, c3 = st.columns(3)
        now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        if c1.button("Approve finding", type="primary", icon=":material/check_circle:", width="stretch"):
            st.session_state.decisions[r["_key"]] = ("approved", now); st.rerun()
        if c2.button("Reject (false alarm / wrong pairing)", icon=":material/cancel:", width="stretch"):
            st.session_state.decisions[r["_key"]] = ("rejected", now); st.rerun()
        if c3.button("Escalate", icon=":material/flag:", width="stretch"):
            st.session_state.decisions[r["_key"]] = ("escalated", now); st.rerun()
        st.caption(f"Current decision: {r['decision']}" + (f" ({r['decided at']})" if r["decided at"] else ""))

with tab3:
    st.subheader("Does the AI actually help? Same labelled data, three methods")
    sets = {"Realistic 1C comments (shortened / generic / blank)": "results_realistic",
            "Easy (1C comment repeats the e-invoice goods text)": "results"}
    sets = {k: v for k, v in sets.items() if os.path.exists(f"{v}/metrics.json")}
    if not sets:
        st.info("Run `python3 evaluate.py data` (and `python3 evaluate.py data_realistic --out results_realistic`) first.")
    else:
        rd = sets[st.radio("Test month", list(sets), horizontal=True)]
        mm = json.load(open(f"{rd}/metrics.json", encoding="utf-8"))
        METHOD_NAMES = {"1_exact": "Exact (VLOOKUP)", "2_fuzzy": "Rules + fuzzy", "3_hybrid_llm": "Hybrid (rules + AI)"}
        # headline: record accuracy per method, delta against today's VLOOKUP approach
        base = mm[0]["record_accuracy"]
        cards = st.columns(len(mm))
        for col, x in zip(cards, mm):
            d = x["record_accuracy"] - base
            col.metric(f"{METHOD_NAMES.get(x['method'], x['method'])} · record accuracy", f"{x['record_accuracy']:.1%}",
                       delta=f"{d * 100:+.1f} pp vs VLOOKUP" if x is not mm[0] else "today's approach",
                       delta_color="normal" if x is not mm[0] else "off")
        ROWS = [("record_accuracy", "Record accuracy", "{:.1%}"), ("pairing_accuracy", "Pairing accuracy", "{:.1%}"),
                ("false_alarms", "False alarms", "{:.0f}"), ("missed_discrepancies", "Missed discrepancies", "{:.0f}"),
                ("wrong_pairings", "Wrong pairings", "{:.0f}"), ("flagged_for_review", "Flagged for review", "{:.0f}"),
                ("seconds", "Runtime, s", "{:.2f}"), ("llm_model", "AI model", "{}"), ("llm_calls", "AI requests", "{:.0f}"),
                ("llm_errors", "AI errors", "{:.0f}")]

        def fmt(v, f):
            return "–" if v is None or (isinstance(v, float) and pd.isna(v)) else f.format(v)
        table = pd.DataFrame({METHOD_NAMES.get(x["method"], x["method"]): [fmt(x.get(k), f) for k, _, f in ROWS]
                              for x in mm}, index=[label for _, label, _ in ROWS])
        st.dataframe(table, width="stretch", height=492)
        if not any(x["method"].startswith("3_") for x in mm):
            st.caption("No AI row yet: run evaluate.py with an API key.")
        if os.path.exists(f"{rd}/per_case_type.csv"):
            st.subheader("Records handled correctly, by case type")
            st.dataframe(pd.read_csv(f"{rd}/per_case_type.csv").rename(columns=METHOD_NAMES), width="stretch",
                         hide_index=True)
        if os.path.exists("results/seeds_summary.csv"):
            st.subheader("Robustness: rules on 10 different generated months (no AI)")
            st.dataframe(pd.read_csv("results/seeds_summary.csv"), width="stretch", hide_index=True)
        if os.path.exists(f"{rd}/failures.csv"):
            st.subheader("Failures (honest list)")
            fl = pd.read_csv(f"{rd}/failures.csv")
            meth = st.selectbox("Method", sorted(fl.method.unique()), index=len(fl.method.unique()) - 1)
            st.dataframe(fl[fl.method == meth], width="stretch", hide_index=True)
        st.caption("Dataset is synthetic with deliberately injected errors (ground truth known). "
                   "Real-world accuracy must be confirmed in a pilot with an accounting firm.")

st.markdown('<div class="mh-foot">MÜHASİB+ · auditable VAT reconciliation · synthetic demo data · '
            'AI proposes, the accountant decides</div>', unsafe_allow_html=True)