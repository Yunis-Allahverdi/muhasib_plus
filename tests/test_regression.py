# HesabAI - end-to-end regression on freshly generated labelled months (no AI, no network)
import csv
import os
import subprocess
import sys

import pytest

import engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def score(d):
    portal, onec = engine.load_csv(os.path.join(d, "portal.csv")), engine.load_csv(os.path.join(d, "onec.csv"))
    with open(os.path.join(d, "truth.csv"), encoding="utf-8") as f:
        truth = {r["record_id"]: r for r in csv.DictReader(f)}
    pred = engine.run_fuzzy(portal, onec)
    ok = wrong = missed = 0
    for rid, t in truth.items():
        p = pred[rid]
        tp = set(filter(None, t["partners"].split(";")))
        dup = t["label"] == "DUPLICATE_IN_1C"
        ok += p["label"] == t["label"] and (dup or not tp or tp == set(p["partners"]))
        wrong += bool(p["partners"]) and not dup and set(p["partners"]) != tp
        missed += t["label"] != "OK" and p["label"] == "OK"
    return ok / len(truth), wrong, missed


@pytest.mark.parametrize("seed", [42, 7, 123])
@pytest.mark.parametrize("realistic", [False, True])
def test_rules_quality(tmp_path, seed, realistic):
    args = [sys.executable, os.path.join(ROOT, "generate_data.py"), str(seed), "150", str(tmp_path)]
    subprocess.run(args + (["--realistic"] if realistic else []), check=True, capture_output=True,
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    acc, wrong, missed = score(tmp_path)
    assert wrong == 0, "rules must never pair a record with the wrong partner"
    assert missed == 0, "no real discrepancy may be reported as OK"
    assert acc >= (0.90 if realistic else 0.95)
