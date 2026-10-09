# HesabAI - robustness check: the non-AI methods on many freshly generated months
# Usage: python3 evaluate_seeds.py [n_seeds]      (default 10; no AI, no network, ~10 s)
# Writes results/seeds_summary.csv (mean / min / max per method and data mode)

import csv
import json
import os
import subprocess
import sys
import tempfile
from statistics import mean

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
SEEDS = [42] + [1000 + i for i in range(N - 1)]
HERE = os.path.dirname(os.path.abspath(__file__))
METRICS = ["record_accuracy", "detection_f1", "false_alarms", "missed_discrepancies", "pairing_accuracy",
           "wrong_pairings"]
env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

rows = []
with tempfile.TemporaryDirectory() as tmp:
    for mode in ["easy", "realistic"]:
        per = {}
        for seed in SEEDS:
            d, out = os.path.join(tmp, f"{mode}{seed}"), os.path.join(tmp, f"r_{mode}{seed}")
            flag = ["--realistic"] if mode == "realistic" else []
            subprocess.run([sys.executable, os.path.join(HERE, "generate_data.py"), str(seed), "150", d] + flag,
                           check=True, capture_output=True, env=env)
            subprocess.run([sys.executable, os.path.join(HERE, "evaluate.py"), d, "--no-llm", "--out", out],
                           check=True, capture_output=True, env=env, cwd=tmp)
            for m in json.load(open(os.path.join(out, "metrics.json"), encoding="utf-8")):
                per.setdefault(m["method"], []).append(m)
        for method, ms in per.items():
            row = {"data": mode, "method": method, "seeds": len(ms)}
            for k in METRICS:
                vals = [m[k] for m in ms]
                row[f"{k}_mean"], row[f"{k}_min"], row[f"{k}_max"] = round(mean(vals), 3), min(vals), max(vals)
            rows.append(row)

os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
path = os.path.join(HERE, "results", "seeds_summary.csv")
with open(path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

print(f"{len(SEEDS)} seeds x 150 cases each\n")
print(f"{'data':10}{'method':10}{'accuracy mean [min-max]':>28}{'false alarms':>16}{'missed':>9}{'wrong pairs':>13}")
for r in rows:
    print(f"{r['data']:10}{r['method']:10}"
          f"{r['record_accuracy_mean']:>12.3f} [{r['record_accuracy_min']:.3f}-{r['record_accuracy_max']:.3f}]"
          f"{r['false_alarms_mean']:>16.1f}{r['missed_discrepancies_max']:>9}{r['wrong_pairings_max']:>13}")
print("\nsaved", path)
