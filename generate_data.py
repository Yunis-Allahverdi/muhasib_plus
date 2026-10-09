# HesabAI - synthetic data generator
# Creates two files that imitate a real month:
#   portal.csv : incoming e-invoices (e-qaimə) from e-taxes.gov.az
#   onec.csv   : purchase documents as booked in 1C
# plus truth.csv : the correct answer for every record (ground truth).
# ALL DATA IS SYNTHETIC. Companies, VÖENs and invoices are invented.

import csv
import random
import os
import sys

#
# Usage: python generate_data.py [seed] [cases] [out_dir] [--realistic]
#   --realistic : 1C comments are typed the way accountants really type them (shortened, generic,
#                 Russian, blank) instead of copying the e-invoice goods text. Same cases, same
#                 amounts and dates as without the flag - only the comments differ.

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SEED = int(ARGS[0]) if len(ARGS) > 0 else 42
N_CASES = int(ARGS[1]) if len(ARGS) > 1 else 150
OUT_DIR = ARGS[2] if len(ARGS) > 2 else "data"
REALISTIC = "--realistic" in sys.argv
random.seed(SEED)
comment_rng = random.Random(SEED + 1)  # separate stream, so --realistic does not change the cases
os.makedirs(OUT_DIR, exist_ok=True)

VAT = 0.18
MONTH = "2026-09"

# Each supplier: official name (as on portal), legal form, and the "other" names
# accountants actually type into 1C (abbreviation, Latin/English, Cyrillic).
SUPPLIERS = [
    ("Azər Tikinti", "MMC", ["Azer Tikinti", "AZƏR TİKİNTİ", "Азер Тикинти"], "Construction materials", ["Sement M400, 50 kisə", "Armatur 12mm, 2 ton", "Kərpic, 3000 əd."]),
    ("Xəzər Ofis Təchizatı", "MMC", ["Caspian Office Supply", "Xezer Ofis", "Хазар Офис"], "Office supplies", ["A4 kağız, 50 qutu", "Printer kartrici HP 85A", "Ofis stulu, 10 əd."]),
    ("Bakı Elektrik Şəbəkəsi", "ASC", ["BEŞ", "Baki Elektrik", "Bakı Elektrik Şəbəkəsi"], "Electricity", ["Elektrik enerjisi, sentyabr", "Elektrik enerjisi, avqust qalığı"]),
    ("Qafqaz Kimya", "MMC", ["Caucasus Chemicals", "Qafqaz Kimya", "Кавказ Химия"], "Chemicals", ["Təmizləyici maye, 200 l", "Dezinfeksiya vasitəsi, 100 l"]),
    ("Abşeron Qida", "MMC", ["Absheron Food", "Abşeron Qida", "Абшерон Гида"], "Food", ["Çay, 40 qutu", "Su 19 l, 60 balon", "Qəhvə dənəli, 10 kq"]),
    ("Şirvan Logistika", "MMC", ["Shirvan Logistics", "Şirvan Log.", "Ширван Логистика"], "Logistics", ["Yükdaşıma Bakı-Gəncə", "Anbar xidməti, sentyabr"]),
    ("Sumqayıt Metal", "ASC", ["Sumgait Metal", "Sumqayit Metal", "Сумгаит Метал"], "Metal", ["Polad boru 89mm", "Metal profil 40x40"]),
    ("Bakı Kompüter Mərkəzi", "MMC", ["BKM", "Baku Computer Center", "Баку Компьютер"], "IT equipment", ["Noutbuk Lenovo, 3 əd.", "Monitor 24\", 5 əd.", "Router, 2 əd."]),
    ("Atlas Mebel", "MMC", ["Atlas Furniture", "Atlas Mebel", "Атлас Мебель"], "Furniture", ["Yazı masası, 6 əd.", "Şkaf, 2 əd."]),
    ("Gəncə Aqro", "MMC", ["Ganja Agro", "Gence Aqro", "Гянджа Агро"], "Agro", ["Toxum, 500 kq", "Gübrə, 1 ton"]),
    ("Lənkəran Çay", "ASC", ["Lankaran Tea", "Lenkeran Cay", "Ленкорань Чай"], "Tea", ["Qara çay, 100 kq", "Yaşıl çay, 30 kq"]),
    ("Mingəçevir Plast", "MMC", ["Mingachevir Plastic", "Mingecevir Plast", "Мингечевир Пласт"], "Plastics", ["Plastik qab, 5000 əd.", "Polietilen torba, 20000 əd."]),
    ("Şəki İpək", "ASC", ["Sheki Silk", "Seki Ipek", "Шеки Ипек"], "Textiles", ["İpək parça, 300 m", "Pambıq parça, 500 m"]),
    ("Azər Tikinti Materialları", "MMC", ["Azer Tikinti Materiallari", "ATM", "Азер Тикинти Материаллары"], "Construction materials (DIFFERENT company)", ["Boya, 40 vedrə", "Kafel, 120 m2"]),
    ("Xəzər Ofis Mebel", "MMC", ["Caspian Office Furniture", "Xezer Mebel", "Хазар Мебель"], "Office furniture (DIFFERENT company)", ["Ofis divanı, 2 əd.", "Konfrans masası"]),
]
# The last two are deliberately confusable with suppliers 0 and 1.

suppliers = []
for name, form, aliases, sector, items in SUPPLIERS:
    voen = str(random.randint(1000000000, 1999999999))
    suppliers.append({"name": name, "form": form, "aliases": aliases, "voen": voen, "items": items})


def official_name(s):
    return f'"{s["name"].upper()}" {s["form"]}'


def typed_name(s, hard):
    # How an accountant types it in 1C. "hard" = alias that string matching can't fix.
    if hard:
        return random.choice(s["aliases"])
    return random.choice([s["name"], f'{s["name"]} {s["form"]}', s["name"].upper()])


def money():
    return round(random.choice([random.uniform(150, 2000), random.uniform(2000, 15000), random.uniform(15000, 60000)]), 2)


def date_in_month(day=None):
    d = day or random.randint(1, 28)
    return f"{MONTH}-{d:02d}"


def shift_date(d, days, same_month=False):
    # same_month=True for records labelled OK: a booking pushed into October would really be a
    # period mismatch, so the truth label would be wrong
    day = int(d[-2:]) + days
    if same_month:
        day = min(day, 30)
    if day <= 30:
        return f"{MONTH}-{day:02d}"
    return f"2026-10-{day - 30:02d}"


GENERIC_COMMENTS = ["Mal alışı", "Xidmət", "Alış", "Поступление товаров", "Поступление услуг", "Qaimə üzrə", "sentyabr"]


def typed_comment(item):
    # what ends up in the 1C comment field
    if not REALISTIC:
        return item
    r = comment_rng.random()
    if r < 0.25:
        return ""
    if r < 0.55:
        return comment_rng.choice(GENERIC_COMMENTS)
    if r < 0.85:
        return item.split(",")[0].split()[0]  # first word only: "Sement", "Printer"
    return item


inv_counter = [0]
c1_counter = [0]


def new_portal_no():
    inv_counter[0] += 1
    return f"MT{random.randint(2600, 2699)}{random.randint(100000, 999999)}"


def new_c1_internal():
    c1_counter[0] += 1
    return f"ПТ-{c1_counter[0]:06d}"


portal, onec, truth = [], [], []
pid, cid = [0], [0]


def add_portal(s, inv_no, date, net, item):
    pid[0] += 1
    rid = f"P{pid[0]:04d}"
    portal.append({"portal_id": rid, "seller_name": official_name(s), "seller_voen": s["voen"],
                   "invoice_no": inv_no, "invoice_date": date, "net_amount": f"{net:.2f}",
                   "vat_amount": f"{round(net * VAT, 2):.2f}", "item_description": item})
    return rid


def add_onec(name, voen, doc_no, date, net, vat, comment):
    cid[0] += 1
    rid = f"C{cid[0]:04d}"
    onec.append({"onec_id": rid, "counterparty": name, "voen": voen, "doc_no": doc_no,
                 "doc_date": date, "net_amount": f"{net:.2f}", "vat_amount": f"{vat:.2f}", "comment": typed_comment(comment)})
    return rid


def onec_doc_no(inv_no, hard):
    # 1C document number as typed: full, last digits only, spaced, or an internal 1C number.
    if hard:
        return new_c1_internal()
    return random.choice([inv_no, inv_no[-6:], f"{inv_no[:2]} {inv_no[2:6]} {inv_no[6:]}", inv_no.lower()])


def typo_voen(v):
    i = random.randint(0, 9)
    d = str((int(v[i]) + random.randint(1, 9)) % 10)
    return v[:i] + d + v[i + 1:]


def label(rid, side, lab, partners, case_type, case_id):
    truth.append({"record_id": rid, "side": side, "label": lab, "partners": ";".join(partners),
                  "case_type": case_type, "case_id": case_id})


# Case mix. "hard" means the 1C row uses an alias name AND an internal doc number,
# so only amount, date, item description and meaning of the name connect them.
CASE_TYPES = [
    ("clean_easy", 30), ("clean_hard_alias", 18), ("split", 8), ("amount_mismatch", 12),
    ("voen_error", 8), ("missing_in_1c", 10), ("missing_in_portal", 8),
    ("period_mismatch", 6), ("duplicate_1c", 5),
]
weights = [w for _, w in CASE_TYPES]
names = [n for n, _ in CASE_TYPES]

for k in range(N_CASES):
    case_id = f"K{k + 1:03d}"
    ct = random.choices(names, weights)[0]
    s = random.choice(suppliers)
    net = money()
    vat = round(net * VAT, 2)
    date = date_in_month()
    item = random.choice(s["items"])
    inv = new_portal_no()
    hard = random.random() < 0.35  # some error cases are also hard to match
    blank_voen = random.random() < 0.3

    if ct == "clean_easy":
        p = add_portal(s, inv, date, net, item)
        c = add_onec(typed_name(s, False), "" if blank_voen else s["voen"], onec_doc_no(inv, False),
                     shift_date(date, random.randint(0, 2), True), net, vat, item)
        label(p, "portal", "OK", [c], ct, case_id); label(c, "onec", "OK", [p], ct, case_id)

    elif ct == "clean_hard_alias":
        p = add_portal(s, inv, date, net, item)
        c = add_onec(typed_name(s, True), "", onec_doc_no(inv, True),
                     shift_date(date, random.randint(0, 3), True), net, vat, item)
        label(p, "portal", "OK", [c], ct, case_id); label(c, "onec", "OK", [p], ct, case_id)

    elif ct == "split":
        p = add_portal(s, inv, date, net, item)
        part = round(net * random.uniform(0.3, 0.7), 2)
        parts = [part, round(net - part, 2)]
        cs = []
        for x in parts:
            cs.append(add_onec(typed_name(s, hard), "" if blank_voen else s["voen"], onec_doc_no(inv, hard),
                               shift_date(date, random.randint(0, 3), True), x, round(x * VAT, 2), item + " (hissə)"))
        label(p, "portal", "OK", cs, ct, case_id)
        for c in cs:
            label(c, "onec", "OK", [p], ct, case_id)

    elif ct == "amount_mismatch":
        p = add_portal(s, inv, date, net, item)
        kind = random.choice(["swap", "rounding", "net_typo"])
        if kind == "swap":  # digits swapped in VAT
            v = f"{vat:.2f}"
            v2 = v[1] + v[0] + v[2:] if v[0] != v[1] else str(round(vat * 1.1, 2))
            bad_net, bad_vat = net, float(v2)
        elif kind == "rounding":  # VAT calculated wrongly
            bad_net, bad_vat = net, round(vat + random.choice([-1, 1]) * random.uniform(1.5, 40), 2)
        else:  # net typed wrongly
            bad_net = round(net + random.choice([-1, 1]) * random.choice([10, 100, 1000]), 2)
            bad_vat = round(bad_net * VAT, 2)
        c = add_onec(typed_name(s, hard), "" if blank_voen else s["voen"], onec_doc_no(inv, hard),
                     shift_date(date, random.randint(0, 2)), bad_net, bad_vat, item)
        label(p, "portal", "AMOUNT_MISMATCH", [c], ct, case_id); label(c, "onec", "AMOUNT_MISMATCH", [p], ct, case_id)

    elif ct == "voen_error":
        p = add_portal(s, inv, date, net, item)
        c = add_onec(typed_name(s, False), typo_voen(s["voen"]), onec_doc_no(inv, False),
                     shift_date(date, random.randint(0, 2)), net, vat, item)
        label(p, "portal", "VOEN_MISMATCH", [c], ct, case_id); label(c, "onec", "VOEN_MISMATCH", [p], ct, case_id)

    elif ct == "missing_in_1c":
        p = add_portal(s, inv, date, net, item)
        label(p, "portal", "MISSING_IN_1C", [], ct, case_id)

    elif ct == "missing_in_portal":
        c = add_onec(typed_name(s, hard), "" if blank_voen else s["voen"], onec_doc_no(inv, hard),
                     date, net, vat, item)
        label(c, "onec", "MISSING_IN_PORTAL", [], ct, case_id)

    elif ct == "period_mismatch":
        d = date_in_month(random.randint(20, 28))
        p = add_portal(s, inv, d, net, item)
        c = add_onec(typed_name(s, hard), "" if blank_voen else s["voen"], onec_doc_no(inv, hard),
                     shift_date(d, random.randint(12, 20)), net, vat, item)
        label(p, "portal", "PERIOD_MISMATCH", [c], ct, case_id); label(c, "onec", "PERIOD_MISMATCH", [p], ct, case_id)

    elif ct == "duplicate_1c":
        p = add_portal(s, inv, date, net, item)
        dn = onec_doc_no(inv, False)
        nm = typed_name(s, False)
        c1 = add_onec(nm, s["voen"], dn, shift_date(date, 1, True), net, vat, item)
        c2 = add_onec(nm, s["voen"], dn, shift_date(date, random.randint(2, 6)), net, vat, item)
        label(p, "portal", "OK", [c1], ct, case_id)
        label(c1, "onec", "OK", [p], ct, case_id)
        label(c2, "onec", "DUPLICATE_IN_1C", [c1], ct, case_id)

# Shuffle 1C rows so order gives nothing away
random.shuffle(onec)


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


write(os.path.join(OUT_DIR, "portal.csv"), portal)
write(os.path.join(OUT_DIR, "onec.csv"), onec)
write(os.path.join(OUT_DIR, "truth.csv"), truth)

print("seed", SEED, "cases", N_CASES, "realistic comments" if REALISTIC else "")
print("portal rows:", len(portal), " 1C rows:", len(onec), " truth rows:", len(truth))
from collections import Counter
print("case types:", dict(Counter(t["case_type"] for t in truth if t["side"] == "portal" or t["case_type"] == "missing_in_portal")))
print("labels:", dict(Counter(t["label"] for t in truth)))
