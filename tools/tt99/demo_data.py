# Run inside `odoo shell -d tt99_demo`: demo group for the TT99 statements.
from datetime import date

parent = env.company
print("PARENT_CHART", parent.chart_template)
sub = env["res.company"].create(
    {
        "name": "Công ty Con S Demo",
        "country_id": env.ref("base.vn").id,
        "currency_id": env.ref("base.VND").id,
        "street": "Số 9 Duy Tân",
        "city": "Hà Nội",
        "vat": "0100000002",
    }
)
env.user.company_ids |= sub
env["account.chart.template"].with_context(allowed_company_ids=[sub.id]).try_loading("vn", company=sub, install_demo=False)
outsider = env["res.partner"].create({"name": "Khách hàng ngoài tập đoàn", "is_company": True})
supplier = env["res.partner"].create({"name": "Nhà cung cấp ngoài tập đoàn", "is_company": True})


def post(company, day, items, ref):
    cenv = env(context=dict(env.context, allowed_company_ids=[company.id]))
    journal = cenv["account.journal"].search([("company_id", "=", company.id), ("type", "=", "general")], limit=1)
    Account = cenv["account.account"]
    lines = []
    for item in items:
        code, amount = item[0], item[1]
        partner = item[2] if len(item) > 2 else cenv["res.partner"]
        account = Account.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1) or Account.search(
            [("code", "=like", code + "%"), ("company_ids", "in", company.id)], order="code", limit=1
        )
        lines.append((0, 0, {"account_id": account.id, "partner_id": partner.id, "name": ref,
                             "debit": max(amount, 0), "credit": max(-amount, 0)}))
    move = cenv["account.move"].create({"journal_id": journal.id, "date": day, "ref": ref, "line_ids": lines})
    move.action_post()


M = 1_000_000
P, S = parent.partner_id, sub.partner_id
post(parent, date(2025, 1, 2), [("112", 50_000 * M), ("41111", -50_000 * M)], "Góp vốn điều lệ")
post(sub, date(2025, 6, 1), [("112", 10_000 * M), ("41111", -10_000 * M)], "Góp vốn điều lệ")
post(sub, date(2025, 7, 1), [("112", 2_000 * M), ("511", -2_000 * M, outsider)], "Doanh thu trước ngày mua")
post(parent, date(2025, 12, 31), [("221", 11_000 * M, S), ("112", -11_000 * M)], "Mua 80% cổ phần công ty S")
post(parent, date(2026, 1, 5), [("156", 5_000 * M), ("1331", 500 * M), ("3311", -5_500 * M, supplier)], "Mua hàng")
post(parent, date(2026, 2, 1), [("1311", 3_300 * M, S), ("511", -3_000 * M, S), ("33311", -300 * M)], "Bán hàng cho công ty con S")
post(parent, date(2026, 2, 1), [("632", 1_800 * M), ("156", -1_800 * M)], "Giá vốn bán cho S")
post(sub, date(2026, 2, 1), [("156", 3_000 * M), ("1331", 300 * M), ("3311", -3_300 * M, P)], "Mua hàng của công ty mẹ")
post(sub, date(2026, 3, 1), [("1311", 4_950 * M, outsider), ("511", -4_500 * M, outsider), ("33311", -450 * M)], "Bán hàng ra ngoài")
post(sub, date(2026, 3, 1), [("632", 2_000 * M), ("156", -2_000 * M)], "Giá vốn (còn tồn 1.000 hàng mua của mẹ)")
post(sub, date(2026, 4, 1), [("3311", 1_000 * M, P), ("112", -1_000 * M)], "Trả tiền công ty mẹ")
post(parent, date(2026, 4, 1), [("112", 1_000 * M), ("1311", -1_000 * M, S)], "Công ty S trả tiền")
post(sub, date(2026, 4, 15), [("112", 3_000 * M), ("1311", -3_000 * M, outsider)], "Thu tiền khách hàng")
post(sub, date(2026, 5, 1), [("6421", 500 * M), ("112", -500 * M)], "Chi phí quản lý")
post(parent, date(2026, 5, 1), [("6421", 300 * M), ("112", -300 * M)], "Chi phí quản lý")
post(parent, date(2026, 6, 1), [("3311", 3_000 * M, supplier), ("112", -3_000 * M)], "Trả nhà cung cấp")

group = env["vn.consolidation.group"].create(
    {
        "name": "Tập đoàn Demo",
        "parent_company_id": parent.id,
        "member_ids": [(0, 0, {"company_id": sub.id, "method": "full", "ownership_pct": 80, "acquisition_date": date(2025, 12, 31)})],
        "unrealized_ids": [
            (0, 0, {"date": date(2026, 12, 31), "seller_company_id": parent.id, "buyer_company_id": sub.id,
                    "goods_value": 1_000 * M, "margin_pct": 40})
        ],
    }
)
group.member_ids.action_take_snapshot()
env.cr.commit()
print("DEMO_OK", sub.id, group.id)
