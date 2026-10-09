# HesabAI - evaluation: exact vs fuzzy vs hybrid(LLM) on the same labelled data
# Usage: python3 evaluate.py [data_dir] [--no-llm] [--out results_dir]
# Writes <out>/metrics.json, <out>/per_case_type.csv, <out>/failures.csv (default out: results)

import csv
import json
import os
import sys
from collections import Counter, defaultdict

import engine
import llm

DATA = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "data"
NO_LLM = "--no-llm" in sys.argv
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "results"
os.makedirs(OUT, exist_ok=True)

portal = engine.load_csv(os.path.join(DATA, "portal.csv"))
onec = engine.load_csv(os.path.join(DATA, "onec.csv"))
with open(os.path.join(DATA, "truth.csv"), encoding="utf-8") as f:
    truth = {r["record_id"]: r for r in csv.DictReader(f)}

print("portal:", len(portal), " 1C:", len(onec), " labelled records:", len(truth))


def score(pred, name):
    tp = fp = fn = tn = 0
    type_ok = 0
    rec_ok = 0
    match_total = match_ok = 0
    review = 0
    wrong_pair = 0  # paired with the wrong record(s): the dangerous error, it hides the real discrepancy
    per_type = defaultdict(lambda: [0, 0])
    fails = []
    for rid, t in truth.items():
        p = pred[rid]
        true_pos = t["label"] != "OK"
        pred_pos = p["label"] != "OK"
        if true_pos and pred_pos: tp += 1
        if not true_pos and pred_pos: fp += 1
        if true_pos and not pred_pos: fn += 1
        if not true_pos and not pred_pos: tn += 1
        if true_pos and p["label"] == t["label"]: type_ok += 1
        if p.get("needs_review") or pred_pos: review += 1  # each record counted once
        t_part = set(filter(None, t["partners"].split(";")))
        p_part = set(p["partners"])
        partner_ok = True
        if t_part and t["label"] != "DUPLICATE_IN_1C":
            match_total += 1
            partner_ok = t_part == p_part
            match_ok += partner_ok
        if p_part and t["label"] != "DUPLICATE_IN_1C" and p_part != t_part:
            wrong_pair += 1
        ok = p["label"] == t["label"] and partner_ok
        rec_ok += ok
        per_type[t["case_type"]][0] += ok
        per_type[t["case_type"]][1] += 1
        if not ok:
            fails.append({"method": name, "record_id": rid, "case_type": t["case_type"], "true_label": t["label"],
                          "pred_label": p["label"], "true_partners": ";".join(sorted(t_part)),
                          "pred_partners": ";".join(sorted(p_part)), "how": p["how"],
                          "evidence": " | ".join(p["evidence"])})
    n = len(truth)
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    m = {"method": name, "records": n, "record_accuracy": rec_ok / n,
         "detection_precision": prec, "detection_recall": rec, "detection_f1": f1,
         "false_alarms": fp, "missed_discrepancies": fn, "true_discrepancies": tp + fn,
         "type_accuracy_on_discrepancies": type_ok / (tp + fn) if tp + fn else 0,
         "pairing_accuracy": match_ok / match_total if match_total else 0,
         "wrong_pairings": wrong_pair,
         "flagged_for_review": review}
    return m, per_type, fails


results, per_types, all_fails = [], {}, []

pred, sec = engine.timed(engine.run_exact, portal, onec)
m, pt, fl = score(pred, "1_exact"); m["seconds"] = round(sec, 3)
results.append(m); per_types["1_exact"] = pt; all_fails += fl

pred, sec = engine.timed(engine.run_fuzzy, portal, onec)
m, pt, fl = score(pred, "2_fuzzy"); m["seconds"] = round(sec, 3)
results.append(m); per_types["2_fuzzy"] = pt; all_fails += fl

if not NO_LLM:
    print("running hybrid with LLM provider:", llm.provider())
    llm_errors = []

    def ask(prompt):
        try:
            return llm.ask_json(prompt)
        except Exception as e:
            llm_errors.append(str(e))
            raise  # run_hybrid flags the record for review
    pred, sec = engine.timed(engine.run_hybrid, portal, onec, ask)
    m, pt, fl = score(pred, "3_hybrid_llm"); m["seconds"] = round(sec, 3)
    m["llm_calls"] = llm.stats["calls"]; m["llm_cached"] = llm.stats["cached"]
    m["llm_in_tokens"] = llm.stats["in_tokens"]; m["llm_out_tokens"] = llm.stats["out_tokens"]
    m["llm_cost_usd"] = round(llm.cost_usd(), 4)
    m["llm_model"] = llm.provider() + ":" + llm.model_name()
    m["llm_retries"] = llm.stats["retries"]
    m["llm_errors"] = len(llm_errors)
    m["records_sent_to_llm"] = m["llm_calls"] + m["llm_cached"]
    if llm_errors:
        print(f"WARNING: {len(llm_errors)} LLM calls failed (first: {llm_errors[0][:200]}). "
              "Answers so far are cached - run again to fill the gaps.")
    results.append(m); per_types["3_hybrid_llm"] = pt; all_fails += fl

# ---- print ----
cols = ["record_accuracy", "detection_precision", "detection_recall", "detection_f1", "false_alarms",
        "missed_discrepancies", "type_accuracy_on_discrepancies", "pairing_accuracy", "wrong_pairings",
        "flagged_for_review", "seconds"]
print()
print(f"{'metric':34}" + "".join(f"{r['method']:>16}" for r in results))
for c in cols:
    print(f"{c:34}" + "".join(f"{r[c]:>16.3f}" if isinstance(r[c], float) else f"{r[c]:>16}" for r in results))
if not NO_LLM:
    r = results[-1]
    print(f"\nLLM: {r['llm_model']}  calls={r['llm_calls']} cached={r['llm_cached']} "
          f"tokens in/out={r['llm_in_tokens']}/{r['llm_out_tokens']} cost=${r['llm_cost_usd']}")

types = sorted({t["case_type"] for t in truth.values()})
print(f"\n{'case type (records correct)':34}" + "".join(f"{k:>16}" for k in per_types))
rows = []
for t in types:
    line = f"{t:34}"
    row = {"case_type": t}
    for k, pt in per_types.items():
        ok, tot = pt[t]
        line += f"{f'{ok}/{tot}':>16}"
        row[k] = f"{ok}/{tot}"
    print(line)
    rows.append(row)

with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
with open(os.path.join(OUT, "per_case_type.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
if all_fails:
    with open(os.path.join(OUT, "failures.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(all_fails[0].keys())); w.writeheader(); w.writerows(all_fails)
print("\nfailures per method:", dict(Counter(x["method"] for x in all_fails)))
print(f"saved {OUT}/metrics.json, {OUT}/per_case_type.csv, {OUT}/failures.csv")
