# Run inside `odoo shell -d <db>` after full_data.py: IFRS adjustments of the demo group.
#
# - IFRS 16: the office rents of the parent and the subsidiary are prepaid
#   expenses under VAS; under IFRS they are 5-year leases from 01/01/2025,
#   paid yearly in advance, discounted at 8%.
# - IFRS 9: expected credit losses of 2% of trade receivables at each
#   reporting date, on top of the VAS provision (reversed the next day).
# - IAS 12: deferred tax at 20% on the cumulative IFRS adjustments (reversed).
from datetime import date

from dateutil.relativedelta import relativedelta

M = 1_000_000
RATE = 0.08
YEARS = 5
CUTOFF = date(2026, 9, 30)
REPORTING_DATES = [date(2025, 12, 31), CUTOFF]
group = env["vn.consolidation.group"].search([], limit=1)
P = group.parent_company_id
S = group.member_ids.filtered(lambda m: m.method == "full").company_id
stats = {"entries": 0}

# Journal names in every installed language (journals created before the translations were loaded).
for journal in env["account.journal"].search([("vn_ledger", "=", "ifrs")]):
    for lang, _name in env["res.lang"].get_installed():
        lang_env = env(context=dict(env.context, lang=lang))
        journal.with_env(lang_env).name = lang_env._("IFRS Adjustments")


def cenv(company):
    return env(context=dict(env.context, allowed_company_ids=[company.id]))


def acc(company, code):
    Account = cenv(company)["account.account"]
    account = Account.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1)
    return account or Account.search([("code", "=like", code + "%"), ("company_ids", "in", company.id)], order="code", limit=1)


def ifrs_journal(company):
    return cenv(company)["account.journal"].search([("company_id", "=", company.id), ("vn_ledger", "=", "ifrs")], limit=1)


def post(company, day, ref, items, reverse=False):
    lines = [(0, 0, {"account_id": acc(company, code).id, "name": ref, "debit": max(round(a), 0), "credit": max(-round(a), 0)})
             for code, a in items if round(a)]
    move = cenv(company)["account.move"].create(
        {"journal_id": ifrs_journal(company).id, "date": day, "ref": ref, "line_ids": lines}
    )
    move.action_post()
    stats["entries"] += 1
    if reverse:
        reversal = move._reverse_moves([{"date": day + relativedelta(days=1), "ref": f"Reversal: {ref}"}])
        reversal.action_post()
        stats["entries"] += 1
    return move


# ---------------------------------------------------------------- IFRS 16
for company, payment in ((P, 1_200 * M), (S, 600 * M)):
    annuity = sum(1 / (1 + RATE) ** k for k in range(1, YEARS))
    liability = payment * annuity
    rou = payment + liability
    monthly_depreciation = rou / (YEARS * 12)
    monthly_rent = payment / 12
    post(company, date(2025, 1, 2), "IFRS 16 - lease recognised",
         [("212", rou), ("34122", -liability), ("2421", -payment)])
    month = date(2025, 1, 1)
    while month <= CUTOFF:
        end = month + relativedelta(months=1, days=-1)
        if month == date(2026, 1, 1):
            # The second yearly payment reduces the lease liability instead of being a prepaid expense.
            post(company, date(2026, 1, 2), "IFRS 16 - lease payment", [("34122", payment), ("2421", -payment)])
            liability -= payment
        interest = liability * RATE / 12
        post(company, end, f"IFRS 16 - {month:%m/%Y}", [
            ("2421", monthly_rent), ("6427", -monthly_rent),         # VAS rent expense reversed
            ("6424", monthly_depreciation), ("2142", -monthly_depreciation),
            ("6351", interest), ("34122", -interest),
        ])
        liability += interest  # interest accrues into the liability
        month += relativedelta(months=1)
    for day in REPORTING_DATES:
        # Next yearly payment falls due within 12 months: current portion of the lease liability.
        post(company, day, "IFRS 16 - current portion of lease liability",
             [("34122", payment), ("34121", -payment)], reverse=day != CUTOFF)

# ---------------------------------------------------------------- IFRS 9 and IAS 12
for company in (P, S):
    for day in REPORTING_DATES:
        AML = cenv(company)["account.move.line"]
        domain = [("company_id", "=", company.id), ("parent_state", "=", "posted"), ("date", "<=", day)]
        receivables = sum(AML.search(domain + [("account_id", "=", acc(company, "1311").id)]).mapped("balance"))
        vas_allowance = -sum(AML.search(domain + [("account_id", "=", acc(company, "22931").id),
                                                  ("journal_id.vn_ledger", "!=", "ifrs")]).mapped("balance"))
        top_up = max(receivables, 0) * 0.02 - vas_allowance
        post(company, day, "IFRS 9 - expected credit losses", [("6426", top_up), ("22931", -top_up)], reverse=day != CUTOFF)
        # Deferred tax on the IFRS adjustments booked so far (profit or loss, net of reversals).
        pl_lines = AML.search(domain + [("journal_id.vn_ledger", "=", "ifrs")]).filtered(
            lambda line: line.account_id.with_company(company).code[:1] in "5678"
            and not line.account_id.with_company(company).code.startswith("821"))
        difference = -sum(pl_lines.mapped("balance"))  # IFRS profit minus VAS profit, cumulative
        tax = -difference * 0.20
        post(company, day, "IAS 12 - deferred tax on IFRS adjustments",
             [("243", tax), ("8212", -tax)] if tax > 0 else [("8212", -tax), ("347", tax)], reverse=day != CUTOFF)

env.cr.commit()
print("IFRS_DEMO", stats)
