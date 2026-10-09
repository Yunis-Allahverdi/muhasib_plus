# HesabAI - unit tests for the reconciliation engine.  Run:  python -m pytest -q
import pytest

import engine

SUP = {"name": '"AZƏR TİKİNTİ" MMC', "voen": "1234567890"}
DECOY = {"name": '"AZƏR TİKİNTİ MATERİALLARI" MMC', "voen": "1987654321"}


def P(pid, inv="MT2601123456", date="2026-09-10", net=1000.0, sup=SUP, item="Sement M400, 50 kisə"):
    return engine.prepare([{"portal_id": pid, "seller_name": sup["name"], "seller_voen": sup["voen"],
                            "invoice_no": inv, "invoice_date": date, "net_amount": str(net),
                            "vat_amount": f"{round(net * 0.18, 2)}", "item_description": item}],
                          engine.PORTAL_COLS, "portal")[0]


def C(cid, name="Azer Tikinti", voen="", doc="MT2601123456", date="2026-09-11", net=1000.0, vat=None, comment=""):
    return engine.prepare([{"onec_id": cid, "counterparty": name, "voen": voen, "doc_no": doc, "doc_date": date,
                            "net_amount": str(net), "vat_amount": str(round(net * 0.18, 2) if vat is None else vat),
                            "comment": comment}], engine.ONEC_COLS, "onec")[0]


# ---------- normalisation and parsing ----------
@pytest.mark.parametrize("raw, want", [
    ('"BAKI ELEKTRİK ŞƏBƏKƏSİ" ASC', "baki elektrik sebekesi"),
    ("Азер Тикинти", "azer tikinti"),
    ("Absheron Food MMC", "abseron food"),
    ("Şirvan Log.", "sirvan log"),
])
def test_norm_name(raw, want):
    assert engine.norm_name(raw) == want


@pytest.mark.parametrize("raw, want", [("1234.56", 1234.56), ("1 234,56", 1234.56), ("1,234.56", 1234.56),
                                       ("1.234,56", 1234.56), ("", 0.0)])
def test_parse_amount(raw, want):
    assert engine.parse_amount(raw) == want


def test_prepare_rejects_bad_input():
    with pytest.raises(ValueError, match="missing columns"):
        engine.prepare([{"portal_id": "P1"}], engine.PORTAL_COLS, "portal")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        P("P1", date="10.09.2026")
    with pytest.raises(ValueError, match="unique"):
        engine.prepare([dict(P("P1")), dict(P("P1"))], engine.PORTAL_COLS, "portal")


def test_doc_number_variants():
    p = P("P1", inv="MT2601123456")
    for doc in ["MT2601123456", "mt2601123456", "MT 2601 123456", "123456"]:
        assert engine.doc_match(p, C("C1", doc=doc)), doc
    assert not engine.doc_match(p, C("C1", doc="ПТ-000012"))


def test_dates_cross_year_boundary():
    assert engine.days_apart({"invoice_date": "2026-12-30"}, {"doc_date": "2027-01-02"}) == 3


# ---------- labels ----------
def test_clean_match_is_ok():
    res = engine.run_fuzzy([P("P1")], [C("C1")])
    assert res["P1"]["label"] == "OK" and res["P1"]["partners"] == ["C1"]
    assert not res["P1"].get("needs_review")


@pytest.mark.parametrize("onec, label", [
    (dict(net=1000.0, vat=108.0), "AMOUNT_MISMATCH"),
    (dict(voen="1234567899"), "VOEN_MISMATCH"),
    (dict(date="2026-10-03"), "PERIOD_MISMATCH"),
])
def test_discrepancy_labels(onec, label):
    res = engine.run_fuzzy([P("P1")], [C("C1", **onec)])
    assert res["P1"]["label"] == label and res["C1"]["label"] == label
    assert res["P1"]["evidence"], "every finding must carry evidence"


def test_missing_both_sides():
    res = engine.run_fuzzy([P("P1")], [C("C1", name="Atlas Mebel", doc="ПТ-000001", net=77.0)])
    assert res["P1"]["label"] == "MISSING_IN_1C" and res["C1"]["label"] == "MISSING_IN_PORTAL"


def test_duplicate_in_1c():
    res = engine.run_fuzzy([P("P1")], [C("C1"), C("C2", date="2026-09-14")])
    assert res["C2"]["label"] == "DUPLICATE_IN_1C" and res["C2"]["partners"] == ["C1"]
    assert res["P1"]["label"] == "OK"


def test_split_invoice():
    res = engine.run_fuzzy([P("P1", net=1000.0)],
                           [C("C1", doc="ПТ-1", net=400.0), C("C2", doc="ПТ-2", net=600.0)])
    assert res["P1"]["label"] == "OK" and sorted(res["P1"]["partners"]) == ["C1", "C2"]


def test_ambiguous_split_is_not_guessed():
    rows = [C(f"C{i}", doc=f"ПТ-{i}", net=n) for i, n in enumerate([400.0, 600.0, 300.0, 700.0])]
    res = engine.run_fuzzy([P("P1", net=1000.0)], rows)
    assert res["P1"]["label"] == "MISSING_IN_1C" and res["P1"].get("needs_review")


# ---------- decoys and weak evidence ----------
def test_decoy_supplier_not_paired_on_name():
    # "Azər Tikinti Materialları" is a different company; different amount, internal number -> no pairing
    res = engine.run_fuzzy([P("P1")], [C("C1", name="Azer Tikinti Materiallari", doc="ПТ-1", net=1500.0)])
    assert res["P1"]["partners"] == []


def test_weak_pairing_always_needs_review():
    # translated name + internal 1C number: only amount, date and goods text connect them
    res = engine.run_fuzzy([P("P1")], [C("C1", name="Caspian Construction", doc="ПТ-1", comment="Sement M400")])
    assert res["P1"]["partners"] == ["C1"]
    assert res["P1"]["needs_review"] and res["C1"]["needs_review"]
    assert res["P1"]["confidence"] <= 0.7


def test_weak_evidence_with_two_candidates_is_not_guessed():
    rows = [C("C1", name="Caspian Construction", doc="ПТ-1", comment="Sement"),
            C("C2", name="Azer Tikinti Materiallari", doc="ПТ-2", comment="Sement")]
    res = engine.run_fuzzy([P("P1")], rows)
    assert res["P1"]["partners"] == [] and res["P1"].get("needs_review")


# ---------- AI step: never trusted blindly ----------
def hard_case():
    portal = [P("P1", item="Kərpic, 3000 əd.")]
    onec = [C("C1", name="Caspian Construction", doc="ПТ-1", net=1100.0)]  # alias + internal no + wrong amount
    return portal, onec


def test_ai_pairing_is_flagged_for_review():
    res = engine.run_hybrid(*hard_case(), lambda prompt: {"match_ids": ["C1"], "confidence": 0.9, "reason": "x"},
                            log=lambda *a: None)
    assert res["P1"]["partners"] == ["C1"] and res["P1"]["label"] == "AMOUNT_MISMATCH"
    assert res["P1"]["needs_review"] and res["C1"]["needs_review"] and res["P1"]["how"] == "LLM"


def test_ai_low_confidence_goes_to_review_not_pairing():
    res = engine.run_hybrid(*hard_case(), lambda prompt: {"match_ids": ["C1"], "confidence": 0.3},
                            log=lambda *a: None)
    assert res["P1"]["partners"] == [] and res["P1"]["needs_review"]


@pytest.mark.parametrize("answer", [{"match_ids": ["C999"], "confidence": 0.99}, {}, {"confidence": "high"}, "junk"])
def test_ai_bad_answers_never_pair(answer):
    res = engine.run_hybrid(*hard_case(), lambda prompt: answer, log=lambda *a: None)
    assert res["P1"]["partners"] == []


def test_ai_outage_flags_instead_of_crashing():
    def down(prompt):
        raise RuntimeError("503 UNAVAILABLE")
    res = engine.run_hybrid(*hard_case(), down, log=lambda *a: None)
    assert res["P1"]["label"] == "MISSING_IN_1C" and res["P1"]["needs_review"]


@pytest.mark.parametrize("doc, conflict", [("MT2699000001", True), ("000001", True), ("mt2601123456", False),
                                           ("123456", False), ("ПТ-000012", False), ("", False)])
def test_doc_conflict(doc, conflict):
    # a 1C row quoting another e-invoice number belongs to another invoice; internal numbers prove nothing
    assert engine.doc_conflict(P("P1", inv="MT2601123456"), C("C1", doc=doc)) == conflict


def test_ai_never_sees_rows_that_quote_another_invoice():
    # real failure from the Gemini run: same supplier + goods, 3x amount, different e-invoice number
    portal = [P("P1", inv="MT2637338533", net=14695.89, item="Çay, 40 qutu")]
    onec = [C("C1", name="ABŞERON QIDA", doc="mt2657664742", net=41096.55, comment="Çay, 40 qutu")]
    seen = []
    res = engine.run_hybrid(portal, onec, lambda prompt: seen.append(prompt) or {"match_ids": ["C1"], "confidence": 0.9},
                            log=lambda *a: None)
    assert seen == [] and res["P1"]["label"] == "MISSING_IN_1C" and res["C1"]["label"] == "MISSING_IN_PORTAL"


def test_ai_cannot_take_half_of_another_invoices_split():
    # real failure from the Groq run: two 1C rows add up exactly to invoice P2, but the AI gave one of them
    # to P1 (same supplier name, amount far off)
    portal = [P("P1", inv="MT2600000001", net=6000.0, date="2026-09-27"),
              P("P2", inv="MT2600000002", net=1000.0, date="2026-09-27")]
    onec = [C("C1", name="Кавказ Химия", doc="ПТ-1", net=400.0, date="2026-09-27"),
            C("C2", name="Caucasus Chemicals", doc="ПТ-2", net=600.0, date="2026-09-28")]
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return {"results": [{"portal_id": "P1", "match_ids": ["C1"], "confidence": 0.9},
                            {"portal_id": "P2", "match_ids": ["C1", "C2"], "confidence": 0.7}]}
    res = engine.run_hybrid(portal, onec, fake, log=lambda *a: None, batch=5)
    assert "C1 + C2 cəmi 1000.00" in prompts[0]  # the AI is told about the exact sum
    assert sorted(res["P2"]["partners"]) == ["C1", "C2"] and res["P2"]["label"] == "OK"
    assert res["P1"]["partners"] == [] and res["P1"]["needs_review"]


def test_ai_is_not_called_when_rules_are_sure():
    calls = []
    engine.run_hybrid([P("P1")], [C("C1")], lambda prompt: calls.append(prompt) or {}, log=lambda *a: None)
    assert calls == []


# ---------- quota protection: batching ----------
def batch_case():
    portal = [P(f"P{i}", inv=f"MT26010000{i:02d}", net=1000.0 + i, item="Kərpic") for i in range(1, 6)]
    onec = [C(f"C{i}", name="Caspian Construction", doc=f"ПТ-{i}", net=1100.0 + i) for i in range(1, 6)]
    return portal, onec


def test_batching_sends_several_invoices_per_request():
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        return {"results": [{"portal_id": f"P{i}", "match_ids": [f"C{i}"], "confidence": 0.9, "reason": "x"}
                            for i in range(1, 6)]}
    res = engine.run_hybrid(*batch_case(), fake, log=lambda *a: None, batch=5)
    assert len(prompts) == 1  # 5 invoices, 1 request
    assert all(res[f"P{i}"]["partners"] == [f"C{i}"] and res[f"P{i}"]["needs_review"] for i in range(1, 6))


def test_batch_conflict_keeps_most_confident_and_flags_other():
    def fake(prompt):  # two invoices claim the same 1C row
        return {"results": [{"portal_id": "P1", "match_ids": ["C1"], "confidence": 0.7},
                            {"portal_id": "P2", "match_ids": ["C1"], "confidence": 0.9}]}
    portal, onec = batch_case()
    res = engine.run_hybrid(portal[:2], onec[:2], fake, log=lambda *a: None, batch=5)
    assert res["P2"]["partners"] == ["C1"]
    assert res["P1"]["partners"] == [] and res["P1"]["needs_review"]


def test_batch_answer_missing_an_invoice_is_not_guessed():
    res = engine.run_hybrid(*batch_case(), lambda prompt: {"results": [{"portal_id": "P1", "match_ids": ["C1"],
                                                                         "confidence": 0.9}]},
                            log=lambda *a: None, batch=5)
    assert res["P1"]["partners"] == ["C1"]
    assert res["P2"]["partners"] == [] and res["P2"]["needs_review"]
