# HesabAI - reconciliation engine
# Three methods, same input, same output format:
#   exact  : what an accountant does with VLOOKUP/SUMIF on invoice number
#   fuzzy  : rules + normalisation + fuzzy name matching (no AI)
#   hybrid : fuzzy, then an LLM resolves the records fuzzy could not match
# Output: one finding per record with a label, partner records, confidence and evidence.

import csv
import os
import re
import time
from datetime import date
from rapidfuzz import fuzz

LABELS = ["OK", "AMOUNT_MISMATCH", "VOEN_MISMATCH", "PERIOD_MISMATCH",
          "MISSING_IN_1C", "MISSING_IN_PORTAL", "DUPLICATE_IN_1C"]

LEGAL_FORMS = ["mmc", "asc", "qsc", "llc", "ojsc", "ooo", "oao", "zao", "ltd", "fs", "ммс", "асц", "ооо"]

CYR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
       "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
       "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "c", "ш": "s", "щ": "s", "ъ": "", "ы": "i", "ь": "",
       "э": "e", "ю": "yu", "я": "ya"}
AZ = {"ə": "e", "ı": "i", "i̇": "i", "ö": "o", "ü": "u", "ş": "s", "ç": "c", "ğ": "g"}


PORTAL_COLS = ["portal_id", "seller_name", "seller_voen", "invoice_no", "invoice_date", "net_amount", "vat_amount"]
ONEC_COLS = ["onec_id", "counterparty", "voen", "doc_no", "doc_date", "net_amount", "vat_amount"]
DATE_WINDOW = 25  # max days between portal and 1C date for amount-based pairing


def parse_amount(s):
    # "1234.56", "1 234,56", "1,234.56", "" -> float
    s = str(s or "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def prepare(rows, cols, side):
    # validates columns, dates and amounts; raises ValueError with a readable message
    missing = [c for c in cols if c not in (rows[0] if rows else {})]
    if missing:
        raise ValueError(f"{side}: missing columns {missing}")
    for i, r in enumerate(rows, start=2):
        for k in cols:
            r[k] = str(r.get(k) or "").strip()
        r.setdefault("item_description" if side == "portal" else "comment", "")
        d = r["invoice_date" if side == "portal" else "doc_date"][:10]
        try:
            date.fromisoformat(d)
        except ValueError:
            raise ValueError(f"{side} row {i}: date '{d}' is not YYYY-MM-DD")
        r["invoice_date" if side == "portal" else "doc_date"] = d
        try:
            r["net"] = parse_amount(r["net_amount"])
            r["vat"] = parse_amount(r["vat_amount"])
        except ValueError:
            raise ValueError(f"{side} row {i}: amount '{r['net_amount']}' / '{r['vat_amount']}' is not a number")
    ids = [r[cols[0]] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{side}: {cols[0]} values must be unique")
    return rows


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    side = "portal" if rows and "portal_id" in rows[0] else "onec"
    return prepare(rows, PORTAL_COLS if side == "portal" else ONEC_COLS, side)


def norm_name(s):
    s = s.lower().replace("İ".lower(), "i")
    s = "".join(CYR.get(ch, ch) for ch in s)
    for a, b in AZ.items():
        s = s.replace(a, b)
    s = s.replace("sh", "s").replace("ch", "c").replace("gh", "g")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [w for w in s.split() if w not in LEGAL_FORMS]
    return " ".join(words)


def norm_doc(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def day_index(d):
    return date.fromisoformat(d[:10]).toordinal()  # real calendar days, safe across months and years


def days_apart(p, c):
    return abs(day_index(c["doc_date"]) - day_index(p["invoice_date"]))


def month_of(d):
    return d[:7]


def name_sim(p, c):
    return fuzz.token_sort_ratio(norm_name(p["seller_name"]), norm_name(c["counterparty"]))


def strong_supplier(p, c):
    return name_sim(p, c) >= 85 or (c["voen"] and c["voen"] == p["seller_voen"])


def partial_name(p, c):
    # 1C name is a shortened form of the portal name: "Baki Elektrik" / "Bakı Elektrik Şəbəkəsi", "Şirvan Log."
    # Weak on its own: "Xəzər Ofis" also fits the decoy "Xəzər Ofis Mebel", so it is only used with amount + date.
    a, b = norm_name(p["seller_name"]).split(), norm_name(c["counterparty"]).split()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if not short or len(short) == len(long_):
        return False
    j = 0
    for t in short:
        while j < len(long_) and not (len(t) >= 3 and long_[j].startswith(t)):
            j += 1
        if j == len(long_):
            return False
        j += 1
    return True


def item_match(p, c):
    # 1C comment repeats the goods/services text of the e-invoice
    a, b = norm_name(p.get("item_description", "")), norm_name(c.get("comment", ""))
    return bool(a and b) and fuzz.token_set_ratio(a, b) >= 90


def weak_supplier_evidence(p, c):
    ev = []
    if partial_name(p, c):
        ev.append(f"1C adı portal adının qısaldılmış formasıdır ('{c['counterparty']}')")
    if item_match(p, c):
        ev.append(f"Mal/xidmət təsviri uyğundur ('{c['comment']}')")
    return ev


def doc_match(p, c):
    a, b = norm_doc(p["invoice_no"]), norm_doc(c["doc_no"])
    if not b:
        return False
    if a == b:
        return True
    return len(b) >= 6 and b.isdigit() and a.endswith(b)


# ---------- labelling a confirmed match (shared by all methods) ----------
def label_match(p, cs):
    net = round(sum(c["net"] for c in cs), 2)
    vat = round(sum(c["vat"] for c in cs), 2)
    ev = []
    if abs(net - p["net"]) > 0.05 or abs(vat - p["vat"]) > 0.05:
        ev.append(f"Portal: net {p['net']:.2f}, ƏDV {p['vat']:.2f}; 1C: net {net:.2f}, ƏDV {vat:.2f}")
        return "AMOUNT_MISMATCH", ev
    bad = [c for c in cs if c["voen"] and c["voen"] != p["seller_voen"]]
    if bad:
        ev.append(f"Portal VÖEN {p['seller_voen']}, 1C VÖEN {bad[0]['voen']}")
        return "VOEN_MISMATCH", ev
    months = {month_of(c["doc_date"]) for c in cs}
    if months != {month_of(p["invoice_date"])}:
        ev.append(f"Portal tarix {p['invoice_date']}, 1C tarix {', '.join(c['doc_date'] for c in cs)}")
        return "PERIOD_MISMATCH", ev
    if len(cs) > 1:
        ev.append(f"{len(cs)} 1C sənədi cəmi portal qaiməsinə bərabərdir ({net:.2f})")
    return "OK", ev


def finalize(portal, onec, matches, duplicates, review, method):
    # matches: list of (portal_row, [1C rows], confidence, how, evidence list)
    out = {}
    used_c = set()
    for p, cs, conf, how, ev in matches:
        lab, ev2 = label_match(p, cs)
        ids = [c["onec_id"] for c in cs]
        out[p["portal_id"]] = {"record_id": p["portal_id"], "side": "portal", "label": lab, "partners": ids,
                               "confidence": conf, "how": how, "evidence": ev + ev2}
        for c in cs:
            used_c.add(c["onec_id"])
            out[c["onec_id"]] = {"record_id": c["onec_id"], "side": "onec", "label": lab,
                                 "partners": [p["portal_id"]], "confidence": conf, "how": how, "evidence": ev + ev2}
    for c, orig in duplicates:
        used_c.add(c["onec_id"])
        out[c["onec_id"]] = {"record_id": c["onec_id"], "side": "onec", "label": "DUPLICATE_IN_1C",
                             "partners": [orig["onec_id"]], "confidence": 0.95, "how": "duplicate rule",
                             "evidence": [f"Eyni kontragent, sənəd nömrəsi və məbləğ: {orig['onec_id']}"]}
    for p in portal:
        if p["portal_id"] not in out:
            out[p["portal_id"]] = {"record_id": p["portal_id"], "side": "portal", "label": "MISSING_IN_1C",
                                   "partners": [], "confidence": review.get(p["portal_id"], 0.9),
                                   "how": "no match", "evidence": ["1C-də uyğun sənəd tapılmadı"]}
    for c in onec:
        if c["onec_id"] not in out:
            out[c["onec_id"]] = {"record_id": c["onec_id"], "side": "onec", "label": "MISSING_IN_PORTAL",
                                 "partners": [], "confidence": review.get(c["onec_id"], 0.9),
                                 "how": "no match", "evidence": ["Portalda uyğun e-qaimə tapılmadı"]}
    for rid, conf in review.items():
        if rid in out:
            out[rid]["needs_review"] = True
            if out[rid]["how"] == "no match":
                out[rid]["evidence"] = out[rid]["evidence"] + [
                    "Mümkün uyğunluq var, amma qeyri-müəyyəndir: mühasib yoxlamalıdır"]
    return out


# ---------- duplicates ----------
def find_duplicates(onec, key_fn):
    seen, dups, rest = {}, [], []
    for c in sorted(onec, key=lambda r: (r["doc_date"], r["onec_id"])):
        k = key_fn(c)
        if k in seen:
            dups.append((c, seen[k]))
        else:
            seen[k] = c
            rest.append(c)
    return dups, rest


# ---------- method 1: exact (VLOOKUP / SUMIF baseline) ----------
def run_exact(portal, onec):
    dups, pool = find_duplicates(onec, lambda c: (c["counterparty"], c["doc_no"], c["net"]))
    by_doc = {}
    for c in pool:
        by_doc.setdefault(c["doc_no"].strip(), []).append(c)
    matches = []
    for p in portal:
        cs = by_doc.get(p["invoice_no"].strip())
        if cs:
            matches.append((p, cs, 1.0, "exact invoice number", [f"Qaimə nömrəsi eynidir: {p['invoice_no']}"]))
    return finalize(portal, onec, matches, dups, {}, "exact")


# ---------- method 2: rules + fuzzy ----------
def fuzzy_pass(portal, pool):
    matches, used_p, used_c = [], set(), set()
    review = {}  # record_id -> confidence, for records the accountant must look at
    # pass A: invoice number (normalised) + name or VÖEN agreement; groups split rows
    for p in portal:
        cs = [c for c in pool if c["onec_id"] not in used_c and doc_match(p, c)
              and (name_sim(p, c) >= 70 or c["voen"] == p["seller_voen"])]
        if cs:
            matches.append((p, cs, 0.95, "invoice no + name/VÖEN",
                            [f"Qaimə nömrəsi uyğundur, ad oxşarlığı {max(name_sim(p, c) for c in cs):.0f}%"]))
            used_p.add(p["portal_id"])
            used_c.update(c["onec_id"] for c in cs)
    # pass B: same supplier (name >= 85 or VÖEN) + same amount + close date; closest date wins
    for p in portal:
        if p["portal_id"] in used_p:
            continue
        cand = [c for c in pool if c["onec_id"] not in used_c and strong_supplier(p, c)
                and abs(c["net"] - p["net"]) < 0.01 and days_apart(p, c) <= DATE_WINDOW]
        if cand:
            best = min(cand, key=lambda c: (days_apart(p, c), c["onec_id"]))
            matches.append((p, [best], 0.85, "name/VÖEN + amount + date",
                            [f"Ad oxşarlığı {name_sim(p, best):.0f}%, məbləğ eynidir"]))
            used_p.add(p["portal_id"])
            used_c.add(best["onec_id"])
    # pass C: split invoice = two rows of the same supplier summing to the portal amount
    split_pass(portal, pool, matches, used_p, used_c, review, strong_only=True)
    # pass D (weak, needs review): exact amount + close date + shortened name or same goods text,
    # and the pair must be the only candidate in both directions
    left_p = [p for p in portal if p["portal_id"] not in used_p]
    free = [c for c in pool if c["onec_id"] not in used_c]
    opts = {}
    for p in left_p:
        for c in free:
            if abs(c["net"] - p["net"]) < 0.01 and days_apart(p, c) <= DATE_WINDOW:
                ev = weak_supplier_evidence(p, c)
                if ev:
                    opts.setdefault(p["portal_id"], []).append((c, ev))
    taken = {}
    for pid, cs in opts.items():
        for c, _ in cs:
            taken[c["onec_id"]] = taken.get(c["onec_id"], 0) + 1
    for p in left_p:
        cs = opts.get(p["portal_id"], [])
        if len(cs) == 1 and taken[cs[0][0]["onec_id"]] == 1:
            c, ev = cs[0]
            matches.append((p, [c], 0.7, "amount + date + weak name/goods (review)",
                            ["Məbləğ eynidir, tarix fərqi " + f"{days_apart(p, c)} gün"] + ev + [REVIEW_NOTE]))
            used_p.add(p["portal_id"])
            used_c.add(c["onec_id"])
            review[p["portal_id"]] = review[c["onec_id"]] = 0.7
        elif cs:
            review[p["portal_id"]] = 0.5  # several possible 1C rows -> accountant decides
    # pass E (weak split, needs review)
    split_pass(portal, pool, matches, used_p, used_c, review, strong_only=False)
    return matches, used_p, used_c, review


REVIEW_NOTE = "Zəif uyğunluq: mühasib təsdiqi tələb olunur"


def split_pass(portal, pool, matches, used_p, used_c, review, strong_only):
    for p in portal:
        if p["portal_id"] in used_p:
            continue
        cand = []
        for c in pool:
            if c["onec_id"] in used_c or c["net"] >= p["net"] or days_apart(p, c) > DATE_WINDOW:
                continue
            strong = bool(strong_supplier(p, c))
            if strong or (not strong_only and weak_supplier_evidence(p, c)):
                cand.append((c, strong))
        pairs = [(a, b) for i, a in enumerate(cand) for b in cand[i + 1:]
                 if abs(a[0]["net"] + b[0]["net"] - p["net"]) < 0.02]
        if not pairs:
            continue
        if len(pairs) > 1:
            review[p["portal_id"]] = 0.5  # several combinations add up -> do not guess
            continue
        (a, sa), (b, sb) = pairs[0]
        cs = [a, b]
        if sa and sb:
            matches.append((p, cs, 0.8, "split (sum of 2 rows)",
                            ["İki 1C sətrinin cəmi portal məbləğinə bərabərdir"]))
        elif strong_only:
            continue
        else:
            ev = [e for c in cs if not strong_supplier(p, c) for e in weak_supplier_evidence(p, c)]
            matches.append((p, cs, 0.65, "split + weak name/goods (review)",
                            ["İki 1C sətrinin cəmi portal məbləğinə bərabərdir"] + ev + [REVIEW_NOTE]))
            for x in [p["portal_id"]] + [c["onec_id"] for c in cs]:
                review[x] = 0.65
        used_p.add(p["portal_id"])
        used_c.update(c["onec_id"] for c in cs)


def run_fuzzy(portal, onec):
    dups, pool = find_duplicates(onec, lambda c: (norm_name(c["counterparty"]), norm_doc(c["doc_no"]), c["net"]))
    matches, _, _, review = fuzzy_pass(portal, pool)
    return finalize(portal, onec, matches, dups, review, "fuzzy")


# ---------- method 3: hybrid (fuzzy + LLM on what is left) ----------
LLM_PROMPT = """Sən Azərbaycan mühasibatlığında ƏDV üzləşdirməsi üzrə köməkçisən.
Vergi portalından gələn bir e-qaimə və 1C-də hələ heç nəyə uyğunlaşdırılmamış namizəd sənədlər verilib.
Hansı 1C sənəd(lər)inin bu e-qaiməyə aid olduğunu müəyyən et.

Bilməli olduğun hallar:
- 1C-də kontragent adı ingiliscə tərcümə, kiril yazısı və ya abbreviatura ola bilər (məs. "Xəzər" = "Caspian", "BEŞ" = "Bakı Elektrik Şəbəkəsi").
- 1C sənəd nömrəsi daxili nömrə ola bilər (ПТ-...), qaimə nömrəsi ilə üst-üstə düşməyə bilər.
- Bir qaimə 1C-də 2 sətrə bölünə bilər (cəmi bərabər olur).
- Məbləğdə və ya tarixdə səhv ola bilər - bu halda da uyğunlaşdır, fərqi sonra yoxlayacağıq.
- Oxşar adlı FƏRQLİ şirkətlər var (məs. "Azər Tikinti" və "Azər Tikinti Materialları" fərqli şirkətlərdir). Əmin deyilsənsə uyğunlaşdırma.
- Heç biri aid deyilsə boş siyahı qaytar.

E-QAİMƏ (portal):
{portal}

NAMİZƏD 1C SƏNƏDLƏRİ:
{cands}

YALNIZ JSON qaytar:
{{"match_ids": ["C...."], "confidence": 0.0-1.0, "reason": "Azərbaycan dilində qısa səbəb"}}"""


def fmt_p(p):
    return (f"id={p['portal_id']} | satıcı={p['seller_name']} | VÖEN={p['seller_voen']} | nömrə={p['invoice_no']} | "
            f"tarix={p['invoice_date']} | net={p['net']:.2f} | ƏDV={p['vat']:.2f} | mal/xidmət={p['item_description']}")


def fmt_c(c):
    return (f"id={c['onec_id']} | kontragent={c['counterparty']} | VÖEN={c['voen'] or '-'} | sənəd={c['doc_no']} | "
            f"tarix={c['doc_date']} | net={c['net']:.2f} | ƏDV={c['vat']:.2f} | şərh={c['comment']}")


def doc_conflict(p, c):
    # the 1C row quotes an e-invoice number (full or last 6 digits) that is NOT this invoice -> other invoice.
    # Internal 1C numbers (Cyrillic prefix, e.g. "ПТ-000012") say nothing either way.
    raw = c["doc_no"]
    if not raw.strip() or re.search(r"[А-Яа-яЁё]", raw):
        return False
    b = norm_doc(raw)
    looks_like_invoice = (b.isdigit() and len(b) >= 6) or (b[:2] == norm_doc(p["invoice_no"])[:2] and len(b) >= 8)
    return looks_like_invoice and not doc_match(p, c)


def candidates_for(p, free, k=6):
    scored = []
    for c in free:
        dd = abs(day_index(c["doc_date"]) - day_index(p["invoice_date"]))
        if dd > 30 or doc_conflict(p, c):  # hard evidence of a different invoice: never offered to the AI
            continue
        amt = abs(c["net"] - p["net"]) / max(p["net"], 1)
        s = name_sim(p, c) / 100 + max(0, 1 - amt * 2) + (1 if doc_match(p, c) else 0) - dd / 60
        scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


# Several uncertain invoices per request: free tiers limit requests per day, not tokens.
LLM_BATCH_PROMPT = ("""Sən Azərbaycan mühasibatlığında ƏDV üzləşdirməsi üzrə köməkçisən.
Vergi portalından gələn bir neçə e-qaimə verilib; hər birinin altında 1C-də hələ heç nəyə uyğunlaşdırılmamış öz namizəd sənədləri var.
Hər e-qaimə üçün AYRICA müəyyən et ki, hansı 1C sənəd(lər)i ona aiddir. Bir 1C sənədi yalnız bir e-qaiməyə aid ola bilər.

""" + LLM_PROMPT[LLM_PROMPT.index("Bilməli"):LLM_PROMPT.index("E-QAİMƏ (portal)")] + """{blocks}

YALNIZ JSON qaytar, hər e-qaimə üçün bir element:
{{"results": [{{"portal_id": "P....", "match_ids": ["C...."], "confidence": 0.0-1.0, "reason": "Azərbaycan dilində qısa səbəb"}}]}}""")


def parse_answer(ans, cands):
    raw_ids = ans.get("match_ids") or []
    ids = [i for i in (raw_ids if isinstance(raw_ids, list) else [raw_ids]) if i in {c["onec_id"] for c in cands}]
    conf = min(max(float(ans.get("confidence") or 0), 0.0), 1.0)
    return ids, conf, str(ans.get("reason", ""))


def exact_split(p, free):
    # the only pair of free 1C rows (close in date) whose net adds up to this invoice, or None
    rows = [c for c in free if c["net"] < p["net"] and days_apart(p, c) <= DATE_WINDOW and not doc_conflict(p, c)]
    pairs = [(a, b) for i, a in enumerate(rows) for b in rows[i + 1:] if abs(a["net"] + b["net"] - p["net"]) < 0.02]
    return pairs[0] if len(pairs) == 1 else None


def cands_text(cands, hint):
    return "\n".join(fmt_c(c) for c in cands) + (f"\n{hint}" if hint else "")


def ask_group(group, ask_llm):
    # one request for the whole group -> {portal_id: answer dict}
    if len(group) == 1:  # single-invoice prompt (keeps earlier cached answers valid)
        p, cands, hint = group[0]
        return {p["portal_id"]: ask_llm(LLM_PROMPT.format(portal=fmt_p(p), cands=cands_text(cands, hint)))}
    blocks = "\n\n".join(f"### E-QAİMƏ {n}:\n{fmt_p(p)}\nNAMİZƏD 1C SƏNƏDLƏRİ:\n" + cands_text(cands, hint)
                         for n, (p, cands, hint) in enumerate(group, 1))
    ans = ask_llm(LLM_BATCH_PROMPT.format(blocks=blocks)) or {}
    return {str(a.get("portal_id")): a for a in (ans.get("results") or []) if isinstance(a, dict)}


def run_hybrid(portal, onec, ask_llm, min_conf=0.6, log=print, batch=None):
    batch = max(1, batch or int(os.environ.get("HESAB_LLM_BATCH") or 5))
    dups, pool = find_duplicates(onec, lambda c: (norm_name(c["counterparty"]), norm_doc(c["doc_no"]), c["net"]))
    matches, used_p, used_c, review = fuzzy_pass(portal, pool)
    free = [c for c in pool if c["onec_id"] not in used_c]
    left = [p for p in portal if p["portal_id"] not in used_p]
    # two free 1C rows adding up exactly to an unpaired invoice: shown to the AI as a hint, and reserved for
    # that invoice (another invoice may only take them if its own amounts add up)
    splits = {p["portal_id"]: s for p in left for s in [exact_split(p, free)] if s}
    claims = {c["onec_id"]: pid for pid, s in splits.items() for c in s}
    todo = []
    for p in left:
        cands, hint = candidates_for(p, free), ""
        if p["portal_id"] in splits:
            a, b = splits[p["portal_id"]]
            cands = [a, b] + [c for c in cands if c not in (a, b)][:4]
            hint = (f"Qeyd: {a['onec_id']} + {b['onec_id']} cəmi {a['net'] + b['net']:.2f} = bu e-qaimənin net "
                    f"məbləği (bölünmüş qaimə ola bilər)")
        if cands:
            todo.append((p, cands, hint))
    n_req = -(-len(todo) // batch)
    log(f"  fuzzy matched {len(used_p)} portal records; sending {len(todo)} to the LLM in {n_req} request(s)")
    proposals = []  # (confidence, portal row, [1C rows], reason)
    for i in range(0, len(todo), batch):
        group = todo[i:i + batch]
        try:
            answers = ask_group(group, ask_llm)
        except Exception as e:  # AI down / quota / budget: never guess, hand the records to the accountant
            log(f"  LLM failed for {', '.join(p['portal_id'] for p, _, _ in group)}: {e}")
            for p, _, _ in group:
                review[p["portal_id"]] = 0.0
            continue
        for p, cands, _ in group:
            if p["portal_id"] not in answers:  # the AI skipped this invoice
                log(f"  LLM failed for {p['portal_id']}: no answer in the batch")
                review[p["portal_id"]] = 0.0
                continue
            try:
                ids, conf, reason = parse_answer(answers[p["portal_id"]] or {}, cands)
            except Exception as e:  # malformed answer for this invoice
                log(f"  LLM failed for {p['portal_id']}: unreadable answer ({e})")
                review[p["portal_id"]] = 0.0
                continue
            if ids:
                proposals.append((conf, p, [c for c in cands if c["onec_id"] in ids], reason))
    # most confident proposal first; a 1C row already claimed by a stronger proposal is not reused
    for conf, p, cs, reason in sorted(proposals, key=lambda x: (-x[0], x[1]["portal_id"])):
        ids = [c["onec_id"] for c in cs]
        # a row that completes another invoice's exact split goes to that invoice, unless this one adds up too
        steals = any(claims.get(x, p["portal_id"]) != p["portal_id"] for x in ids) and \
            abs(sum(c["net"] for c in cs) - p["net"]) >= 0.02
        if conf >= min_conf and not used_c.intersection(ids) and not steals:
            matches.append((p, cs, conf, "LLM", [f"AI: {reason} (əminlik {conf:.2f})",
                                                 "AI uyğunlaşdırması: mühasib təsdiqi tələb olunur"]))
            used_c.update(ids)
            for x in [p["portal_id"]] + ids:  # AI pairings are proposals, not decisions
                review[x] = conf
        else:  # AI unsure, or two invoices claim the same 1C row -> accountant decides
            review[p["portal_id"]] = conf
            for x in ids:
                if x not in used_c:
                    review[x] = conf
    return finalize(portal, onec, matches, dups, review, "hybrid")


def timed(fn, *a, **k):
    t = time.time()
    r = fn(*a, **k)
    return r, time.time() - t
