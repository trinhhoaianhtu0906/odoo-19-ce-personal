# Run inside `odoo shell -d tt99_full`: cross-check the TT99 statements against the ledger.
from collections import defaultdict
from datetime import date, timedelta

from odoo.addons.l10n_vn_tt99_reports.models.engine import LedgerProvider, evaluate_report

R = lambda xmlid: env.ref(xmlid)  # noqa: E731
B01, B02, B03 = (R("l10n_vn_tt99_reports.report_b01"), R("l10n_vn_tt99_reports.report_b02"),
                 R("l10n_vn_tt99_reports.report_b03_direct"))
B01HN, B02HN = R("l10n_vn_tt99_consolidation.report_b01_hn"), R("l10n_vn_tt99_consolidation.report_b02_hn")
group = env["vn.consolidation.group"].search([], limit=1)
P = group.parent_company_id
S = group.member_ids.filtered(lambda m: m.method == "full").company_id
A = group.member_ids.filtered(lambda m: m.method == "equity").company_id
PERIODS = [(date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 9, 30))]
results = []


def check(label, expected, actual, tolerance=1):
    ok = abs((expected or 0) - (actual or 0)) <= tolerance
    results.append((ok, label, expected, actual))


def run(report, provider, period):
    res = evaluate_report(report, provider, *period)
    return ({i["line"].code: i["value"] or 0 for i in res["lines"]},
            {i["line"].code: i["value_cmp"] or 0 for i in res["lines"]}, res["warnings"])


def ledger(company, date_from=None, date_to=None, exclude_closing=False):
    """{code: balance} straight from the journal items."""
    domain = [("company_id", "=", company.id), ("parent_state", "=", "posted")]
    if date_from:
        domain.append(("date", ">=", date_from))
    if date_to:
        domain.append(("date", "<=", date_to))
    if exclude_closing:
        company_env = env(context=dict(env.context, allowed_company_ids=[company.id]))
        closing = company_env["account.move.line"].search(domain + [("account_id.code", "=like", "911%")]).move_id
        domain.append(("move_id", "not in", closing.ids))
    out = defaultdict(float)
    for account, balance in env["account.move.line"]._read_group(domain, ["account_id"], ["balance:sum"]):
        out[account.with_company(company).code] += balance
    return out


def total(balances, *prefixes):
    return sum(v for k, v in balances.items() if k.startswith(prefixes))


def profit(company, date_from, date_to):
    """Profit after tax from the ledger, closing entries excluded."""
    return -total(ledger(company, date_from, date_to, exclude_closing=True), "5", "6", "7", "8")


def equity(company, day):
    """Total equity at ``day``: 4xx plus every unclosed P&L balance."""
    return -total(ledger(company, None, day), "4", "5", "6", "7", "8", "9")


# ---------------------------------------------------------------- standalone
for company in (P, S, A):
    provider = LedgerProvider(env, company)
    closing_2025 = None
    for period in PERIODS:
        tag = f"{company.name[:28]} {period[1]:%d/%m/%Y}"
        b01, b01_open, w1 = run(B01, provider, period)
        b02, _p, w2 = run(B02, provider, period)
        b03, _p, w3 = run(B03, provider, period)
        check(f"{tag} | B01 không cảnh báo ({len(w1)})", 0, len(w1), 0)
        check(f"{tag} | B01 280 = 440", b01["280"], b01["440"])
        check(f"{tag} | B02 không cảnh báo ({len(w2)})", 0, len(w2), 0)
        check(f"{tag} | B03 không cảnh báo ({len(w3)})", 0, len(w3), 0)
        bal = ledger(company, None, period[1])
        check(f"{tag} | B01 110 = số dư 111,112,113,12811,12881", total(bal, "111", "112", "113", "12811", "12881"), b01["110"])
        check(f"{tag} | B01 141 = số dư hàng tồn kho 15x", total(bal, "151", "152", "1531", "1541", "155", "156", "157", "158"), b01["141"])
        check(f"{tag} | B01 400 = vốn chủ + lãi lỗ chưa kết chuyển", equity(company, period[1]), b01["400"])
        check(f"{tag} | B01 131 - 312 = số dư 1311", total(bal, "1311"), b01["131"] - b01["312"])
        check(f"{tag} | B02 60 = lãi lỗ trên sổ", profit(company, *period), b02["60"])
        check(f"{tag} | B02 50 = 60 + 51 + 52", b02["50"], b02["60"] + b02["51"] + b02["52"])
        check(f"{tag} | B03 70 = B01 110 cuối kỳ", b01["110"], b03["70"])
        check(f"{tag} | B03 60 = B01 110 đầu kỳ", b01_open["110"], b03["60"])
        if closing_2025:
            diffs = [c for c in b01_open if abs(b01_open[c] - closing_2025.get(c, 0)) > 1]
            check(f"{tag} | B01 đầu 2026 = cuối 2025 (mọi dòng; lệch: {diffs[:5]})", 0, len(diffs), 0)
        closing_2025 = b01

# ---------------------------------------------------------------- consolidated
provider = group._get_provider()
member_s = group.member_ids.filtered(lambda m: m.method == "full")
member_a = group.member_ids.filtered(lambda m: m.method == "equity")
acq_s, acq_a = member_s.acquisition_date, member_a.acquisition_date
e_acq = sum(member_s.snapshot_line_ids.mapped("amount"))
goodwill = 24_000_000_000 - 0.8 * e_acq
unrealized = {u.date: u.amount for u in group.unrealized_ids}


def amort(day):
    months = max(0, (day.year - acq_s.year) * 12 + day.month - acq_s.month)
    return round(goodwill * min(months, 120) / 120)


for period in PERIODS:
    date_from, date_to = period
    tag = f"HỢP NHẤT {date_to:%d/%m/%Y}"
    h01, h01_open, w1 = run(B01HN, provider, period)
    h02, _p, w2 = run(B02HN, provider, period)
    p01, _o, _w = run(B01, LedgerProvider(env, P), period)
    s01, _o, _w = run(B01, LedgerProvider(env, S), period)
    check(f"{tag} | B01-HN không cảnh báo ({w1})", 0, len(w1), 0)
    check(f"{tag} | B02-HN không cảnh báo ({w2})", 0, len(w2), 0)
    check(f"{tag} | B01-HN 280 = 440", h01["280"], h01["440"])
    check(f"{tag} | B01-HN đầu kỳ 280 = 440", h01_open["280"], h01_open["440"])
    check(f"{tag} | B01-HN 261 đầu tư vào công ty con đã loại trừ", 0, h01["261"])
    check(f"{tag} | B01-HN 279 lợi thế thương mại = LTTM - phân bổ lũy kế", goodwill - amort(date_to), h01["279"])
    nci = 0.2 * equity(S, date_to) - 0.0
    check(f"{tag} | B01-HN 429 = 20% vốn chủ công ty con", nci, h01["429"], 2)
    assoc = 6_000_000_000 + 0.3 * (equity(A, date_to) - equity(A, acq_a))
    check(f"{tag} | B01-HN 262 = giá gốc + 30% biến động vốn chủ công ty liên kết", assoc, h01["262"], 2)
    u_end, u_begin = unrealized.get(date_to, 0), unrealized.get(date_from - timedelta(days=1), 0)
    check(f"{tag} | B01-HN 141 = HTK mẹ + con - lãi chưa thực hiện", p01["141"] + s01["141"] - u_end, h01["141"])
    s_from = max(date_from, acq_s + timedelta(days=1))
    pat_s = profit(S, s_from, date_to)
    pat_a = profit(A, max(date_from, acq_a + timedelta(days=1)), date_to)
    intra_dividend = 1_600_000_000 if date_from.year == 2026 else 0
    amort_period = amort(date_to) - amort(date_from - timedelta(days=1))
    expected = (profit(P, date_from, date_to) + pat_s + 0.3 * pat_a - intra_dividend - amort_period
                - (u_end - u_begin) * 0.8)
    check(f"{tag} | B02-HN 60 = LN mẹ + LN con sau mua + 30% LN liên kết - cổ tức nội bộ - phân bổ LTTM - Δ lãi chưa TH", expected, h02["60"], 3)
    check(f"{tag} | B02-HN 62 = 20% LN con sau ngày mua", 0.2 * pat_s, h02["62"], 2)
    check(f"{tag} | B02-HN 27 = 30% LN công ty liên kết", 0.3 * pat_a, h02["27"], 2)
    check(f"{tag} | B02-HN 61 = 60 - 62", h02["60"] - h02["62"], h02["61"])

# ---------------------------------------------------------------- summary
moves = env["account.move"]._read_group([("state", "=", "posted")], ["company_id", "move_type"], ["__count"])
print("VOLUME")
for company, move_type, count in moves:
    print(f"   {company.name:40} {move_type:12} {count}")
print("PAYMENTS", env["account.payment"].search_count([("state", "!=", "draft")]),
      "PARTNERS", env["res.partner"].search_count([]), "PRODUCTS", env["product.product"].search_count([]),
      "ASSETS", env["account.asset.asset"].search_count([]))
fails = [r for r in results if not r[0]]
for ok, label, expected, actual in results:
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f" | kỳ vọng {expected:,.0f} | báo cáo {actual:,.0f}"))
print("TOTAL", len(results), "FAIL", len(fails))
