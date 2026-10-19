# Run inside `odoo shell -d <db>`. Sample group data, 01/2025 - 09/2026.
import random
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

rng = random.Random(2026)
M = 1_000_000
CUTOFF = date(2026, 9, 30)
MONTHS = [date(2025, 1, 1) + relativedelta(months=i) for i in range(21)]  # 01/2025 .. 09/2026
stats = defaultdict(int)

# ---------------------------------------------------------------- companies
VN = env.ref("base.vn")
VND = env.ref("base.VND")
P = env.company


def new_company(vals):
    company = env["res.company"].create({"country_id": VN.id, "currency_id": VND.id, **vals})
    env.user.company_ids |= company
    env["account.chart.template"].with_context(allowed_company_ids=[company.id]).try_loading(
        "vn", company=company, install_demo=False
    )
    return company


S = new_company({"name": "Công ty TNHH Tricasia Phân phối", "street": "KCN Thăng Long", "city": "Hà Nội",
                 "state_id": env.ref("base.state_vn_VN-HN").id, "vat": "0109000002"})
A = new_company({"name": "Công ty CP Tricasia Công nghệ", "street": "Quận 1", "city": "TP Hồ Chí Minh",
                 "state_id": env.ref("base.state_vn_VN-SG").id, "vat": "0319000003"})
COMPANIES = [P, S, A]
env.user.company_ids = [(6, 0, [c.id for c in COMPANIES])]
# The shell runs as OdooBot: give the admin user the new companies too.
env.ref("base.user_admin").company_ids = [(6, 0, [c.id for c in COMPANIES])]


def cenv(company):
    return env(context=dict(env.context, allowed_company_ids=[company.id]))


ACC_CACHE = {}


def acc(company, code):
    key = (company.id, code)
    if key not in ACC_CACHE:
        Account = cenv(company)["account.account"]
        account = Account.search([("code", "=", code), ("company_ids", "in", company.id)], limit=1)
        account = account or Account.search(
            [("code", "=like", code + "%"), ("company_ids", "in", company.id)], order="code", limit=1
        )
        assert account, (company.name, code)
        ACC_CACHE[key] = account
    return ACC_CACHE[key]


def journal(company, jtype):
    return cenv(company)["account.journal"].search([("company_id", "=", company.id), ("type", "=", jtype)], limit=1)


def tax(company, name):
    return env.ref(f"account.{company.id}_{name}")


# Payments hit the bank account directly (no 1131/1132 outstanding accounts).
for company in COMPANIES:
    bank = journal(company, "bank")
    for line in bank.inbound_payment_method_line_ids | bank.outbound_payment_method_line_ids:
        line.payment_account_id = bank.default_account_id
    if "account.fiscal.year" in env:
        for year in (2025, 2026):
            env["account.fiscal.year"].create(
                {"name": f"Năm tài chính {year}", "date_from": date(year, 1, 1), "date_to": date(year, 12, 31),
                 "company_id": company.id}
            )

# ---------------------------------------------------------------- partners
NAMES = ["Minh Phát", "Hoàng Long", "An Khang", "Thành Công", "Việt Tiến", "Phú Gia", "Đại Nam", "Tân Thịnh",
         "Hưng Thịnh", "Bảo Minh", "Sao Mai", "Kim Long", "Thiên Phú", "Nam Việt", "Đông Á", "Hải Âu", "Trường Sơn",
         "Ngọc Lan", "Phương Đông", "Quang Huy", "Hòa Bình", "Tiến Đạt", "Phúc Lộc", "Vạn Xuân", "Hà Thành",
         "Sông Hồng", "Cửu Long", "Thăng Long", "Bình Minh", "Mai Linh", "Hồng Hà", "Gia Phát", "Lạc Việt",
         "Đức Tín", "Thịnh Vượng", "Tràng An", "Kinh Bắc", "Duy Tân", "Hoàn Cầu", "Trí Việt"]
TRADES = ["Thương mại", "Công nghệ", "Xây dựng", "Dịch vụ", "Giải pháp", "Đầu tư", "Sản xuất"]
CITIES = [("Hà Nội", "VN-HN"), ("TP Hồ Chí Minh", "VN-SG"), ("TP Đà Nẵng", "VN-DN"), ("TP Hải Phòng", "VN-HP"),
          ("Bắc Ninh", "VN-56")]
Partner = env["res.partner"]


def make_partner(i, kind):
    city, state = rng.choice(CITIES)
    form = rng.choice(["Công ty TNHH", "Công ty CP"])
    return Partner.create(
        {"name": f"{form} {rng.choice(TRADES)} {NAMES[i % len(NAMES)]}" + ("" if i < len(NAMES) else f" {i}"),
         "is_company": True, "vat": f"{rng.choice(['01', '03', '04'])}{rng.randint(10**7, 10**8 - 1)}",
         "city": city, "state_id": env.ref(f"base.state_vn_{state}").id, "country_id": VN.id,
         "customer_rank": 1 if kind == "customer" else 0, "supplier_rank": 1 if kind == "vendor" else 0}
    )


customers = [make_partner(i, "customer") for i in range(30)]
vendors = [make_partner(i + 30, "vendor") for i in range(12)]
bank_partner = Partner.create({"name": "Ngân hàng TMCP Ngoại thương Việt Nam - CN Hà Nội", "is_company": True,
                               "vat": "0100112437"})
landlord = Partner.create({"name": "Công ty CP Bất động sản Liễu Giai", "is_company": True, "vat": "0101234567"})
minority = Partner.create({"name": "Cổ đông thiểu số S (nhóm cá nhân)"})
employees = Partner.create({"name": "Cán bộ công nhân viên"})
tax_office = Partner.create({"name": "Cục Thuế TP Hà Nội", "is_company": True})
social = Partner.create({"name": "Bảo hiểm xã hội TP Hà Nội", "is_company": True})
stats["partners"] = len(customers) + len(vendors) + 6

# ---------------------------------------------------------------- products
Categ = env["product.category"]
cat_goods = Categ.create({"name": "Hàng hóa thiết bị CNTT"})
cat_service = Categ.create({"name": "Dịch vụ triển khai"})
cat_selling = Categ.create({"name": "Chi phí bán hàng mua ngoài"})
cat_admin = Categ.create({"name": "Chi phí quản lý mua ngoài"})
cat_rent = Categ.create({"name": "Thuê văn phòng trả trước"})
cat_asset = Categ.create({"name": "Tài sản cố định"})
for company in COMPANIES:
    for categ, income, expense in [(cat_goods, "5110", "1560"), (cat_service, "5110", "6427"),
                                   (cat_selling, "5110", "6417"), (cat_admin, "5110", "6427"),
                                   (cat_rent, "5110", "2421"), (cat_asset, "711", "2110")]:
        categ.with_company(company).write({"property_account_income_categ_id": acc(company, income).id,
                                           "property_account_expense_categ_id": acc(company, expense).id})

Product = env["product.product"]
GOODS = [("Laptop doanh nghiệp T14", 18), ("Máy trạm đồ họa Z4", 42), ("Màn hình 27 inch", 5),
         ("Máy in laser A3", 22), ("Switch mạng 48 cổng", 26), ("Bộ phát Wi-Fi 6", 3), ("Ổ cứng SSD 2TB", 4),
         ("Máy chủ rack 2U", 160), ("Thiết bị lưu trữ NAS", 55), ("Bộ lưu điện UPS 3kVA", 14),
         ("Máy chiếu hội nghị", 19), ("Camera an ninh IP", 2.5), ("Tường lửa doanh nghiệp", 48),
         ("Bộ đàm hội nghị", 9), ("Máy quét tài liệu", 11)]
goods = []
for name, cost in GOODS:
    product = Product.create({"name": name, "type": "consu", "categ_id": cat_goods.id,
                              "standard_price": cost * M, "list_price": round(cost * rng.uniform(1.25, 1.45), 1) * M,
                              "taxes_id": False, "supplier_taxes_id": False})
    goods.append(product)
SERVICES = [("Dịch vụ triển khai hệ thống", 35), ("Bảo trì thiết bị năm", 12), ("Đào tạo người dùng", 8),
            ("Tư vấn chuyển đổi số", 50)]
services = [Product.create({"name": n, "type": "service", "categ_id": cat_service.id, "list_price": p * M,
                            "taxes_id": False, "supplier_taxes_id": False}) for n, p in SERVICES]
BOUGHT = {"Vận chuyển giao hàng": (cat_selling, 8), "Quảng cáo trực tuyến": (cat_selling, 30),
          "Điện, nước, internet": (cat_admin, 15), "Phí kiểm toán, tư vấn thuế": (cat_admin, 60),
          "Văn phòng phẩm": (cat_admin, 5), "Thuê văn phòng 12 tháng": (cat_rent, 0),
          "Máy chủ nội bộ": (cat_asset, 0), "Xe ô tô 7 chỗ": (cat_asset, 0)}
bought = {name: Product.create({"name": name, "type": "service", "categ_id": categ.id, "taxes_id": False,
                                "supplier_taxes_id": False, "standard_price": price * M})
          for name, (categ, price) in BOUGHT.items()}
INTRA_PRODUCT = goods[7]  # máy chủ rack: S buys it from P only
SERVER_PRICE = round(INTRA_PRODUCT.list_price * 0.9, -3)
stats["products"] = len(goods) + len(services) + len(bought)

# ---------------------------------------------------------------- posting helpers
stock = defaultdict(lambda: defaultdict(float))  # company -> product -> qty
cogs_month = defaultdict(float)  # (company, month) -> cost
intra_stock = 0.0  # qty of P-sourced servers still held by S


def je(company, day, ref, items):
    lines = []
    for item in items:
        code, amount = item[0], item[1]
        partner = item[2] if len(item) > 2 else Partner
        if not round(amount):
            continue
        lines.append((0, 0, {"account_id": acc(company, code).id, "partner_id": partner.id, "name": ref,
                             "debit": max(round(amount), 0), "credit": max(-round(amount), 0)}))
    if not lines:
        return None
    move = cenv(company)["account.move"].create(
        {"journal_id": journal(company, "general").id, "date": day, "ref": ref, "line_ids": lines}
    )
    move.action_post()
    stats["journal_entries"] += 1
    return move


def invoice(company, move_type, partner, day, lines, ref=None):
    env_c = cenv(company)
    sale = move_type.startswith("out")
    vat = tax(company, "tax_sale_vat10" if sale else "tax_purchase_vat10")
    move = env_c["account.move"].create({
        "move_type": move_type, "partner_id": partner.id, "invoice_date": day, "date": day, "ref": ref,
        "journal_id": journal(company, "sale" if sale else "purchase").id,
        "invoice_line_ids": [(0, 0, {"product_id": product.id, "quantity": qty, "price_unit": price,
                                     "tax_ids": [(6, 0, vat.ids)]}) for product, qty, price in lines],
    })
    move.action_post()
    stats[move_type] += 1
    return move


def pay(move, day, ratio=1.0):
    amount = round(move.amount_residual * ratio, -3)
    if amount <= 0 or day > CUTOFF:
        return
    company = move.company_id
    wizard = cenv(company)["account.payment.register"].with_context(
        active_model="account.move", active_ids=move.ids
    ).create({"payment_date": day, "journal_id": journal(company, "bank").id, "amount": amount})
    wizard.action_create_payments()
    stats["payments"] += 1


def free_payment(company, partner, day, amount, inbound, ref):
    env_c = cenv(company)
    payment = env_c["account.payment"].create({
        "payment_type": "inbound" if inbound else "outbound",
        "partner_type": "customer" if inbound else "supplier",
        "partner_id": partner.id, "amount": round(amount, -3), "date": day,
        "journal_id": journal(company, "bank").id, "memo": ref,
    })
    payment.action_post()
    stats["payments"] += 1
    return payment


def day_in(month, low=2, high=27):
    return month.replace(day=rng.randint(low, high))


def month_end(month):
    return month + relativedelta(months=1, days=-1)


def unit_cost(company, product):
    if company == S and product == INTRA_PRODUCT:
        return SERVER_PRICE
    return product.standard_price


def sell(company, partner, day, items):
    """Customer invoice; records goods cost for the monthly COGS entry."""
    lines = []
    for product, qty in items:
        price = product.list_price * rng.uniform(0.95, 1.05) if product.type == "consu" else product.list_price
        lines.append((product, qty, round(price, -3)))
        if product.type == "consu":
            stock[company.id][product.id] -= qty
            cogs_month[(company.id, day.replace(day=1))] += qty * unit_cost(company, product)
    return invoice(company, "out_invoice", partner, day, lines)


def buy_goods(company, partner, day, items, price_of=None):
    lines = []
    for product, qty in items:
        price = price_of(product) if price_of else product.standard_price
        lines.append((product, qty, round(price, -3)))
        stock[company.id][product.id] += qty
    return invoice(company, "in_invoice", partner, day, lines)


# ---------------------------------------------------------------- opening and capital events
je(S, date(2024, 12, 1), "Góp vốn điều lệ", [("1120", 25_000 * M), ("41111", -25_000 * M)])
je(A, date(2024, 12, 15), "Góp vốn điều lệ", [("1120", 20_000 * M), ("41111", -20_000 * M)])
je(P, date(2025, 1, 2), "Góp vốn điều lệ", [("1120", 100_000 * M), ("41111", -100_000 * M)])
je(P, date(2025, 1, 2), "Mua 30% cổ phần Tricasia Công nghệ", [("2220", 6_000 * M, A.partner_id), ("1120", -6_000 * M)])
je(P, date(2025, 1, 6), "Gửi tiết kiệm 3 tháng", [("12811", 10_000 * M, bank_partner), ("1120", -10_000 * M)])
je(P, date(2025, 2, 3), "Gửi tiết kiệm 6 tháng", [("12812", 15_000 * M, bank_partner), ("1120", -15_000 * M)])
je(P, date(2025, 3, 31), "Mua 80% vốn Tricasia Phân phối", [("2210", 24_000 * M, S.partner_id), ("1120", -24_000 * M)])
je(P, date(2025, 4, 1), "Giải ngân vay ngắn hạn", [("1120", 20_000 * M), ("34111", -20_000 * M, bank_partner)])
je(P, date(2025, 4, 7), "Tất toán tiền gửi 3 tháng", [("1120", 10_125 * M), ("12811", -10_000 * M, bank_partner), ("5150", -125 * M)])
je(P, date(2025, 8, 4), "Tất toán tiền gửi 6 tháng", [("1120", 15_390 * M), ("12812", -15_000 * M, bank_partner), ("5150", -390 * M)])
je(P, date(2026, 4, 1), "Trả bớt nợ gốc vay", [("34111", 5_000 * M, bank_partner), ("1120", -5_000 * M)])

# Initial stock so that sales never run the warehouse negative.
for company, share in ((P, 1.0), (S, 0.6)):
    items = [(g, rng.randint(15, 30) * share // 1 + 5) for g in goods if not (company == S and g == INTRA_PRODUCT)]
    for chunk in range(0, len(items), 5):
        buy_goods(company, rng.choice(vendors), date(2025, 1, 3), items[chunk:chunk + 5])

# Rent paid 12 months in advance, then amortised monthly.
for company, rent in ((P, 1_200), (S, 600), (A, 360)):
    for year in (2025, 2026):
        bill = invoice(company, "in_invoice", landlord, date(year, 1, 2), [(bought["Thuê văn phòng 12 tháng"], 1, rent * M)])
        pay(bill, date(year, 1, 5))

# Fixed assets through om_account_asset.
Asset = env["account.asset.asset"]
for company in (P, S):
    categ = env["account.asset.category"].create({
        "name": "Thiết bị và phương tiện", "company_id": company.id, "journal_id": journal(company, "general").id,
        "account_asset_id": acc(company, "2110").id, "account_depreciation_id": acc(company, "2141").id,
        "account_depreciation_expense_id": acc(company, "6424").id, "method_number": 60, "method_period": 1,
        "open_asset": True, "date_first_depreciation": "last_day_period",
    })
    for name, value, day in (("Máy chủ nội bộ", 1_800 * M, date(2025, 2, 10)), ("Xe ô tô 7 chỗ", 1_200 * M, date(2025, 5, 15))):
        if company == S and name.startswith("Xe"):
            continue
        bill = invoice(company, "in_invoice", rng.choice(vendors), day, [(bought[name], 1, value)])
        pay(bill, day + relativedelta(days=10))
        asset = cenv(company)["account.asset.asset"].create({
            "name": name, "category_id": categ.id, "value": value, "date": day, "company_id": company.id,
            "method_number": 60, "date_first_depreciation": "last_day_period",
        })
        asset.validate()
        asset.depreciation_line_ids.filtered(lambda line: line.depreciation_date <= CUTOFF).create_move(post_move=True)
        stats["fixed_assets"] += 1

# ---------------------------------------------------------------- monthly operations
open_sales = []
for month in MONTHS:
    end = month_end(month)
    for company, n_sales, wage in ((P, 6, 800), (S, 7, 500), (A, 0, 450)):
        # Customer invoices
        for _i in range(n_sales):
            customer = rng.choice(customers)
            items = [(g, rng.randint(1, 4)) for g in rng.sample(goods, rng.randint(1, 3)) if g != INTRA_PRODUCT or company == P]
            if company == S and intra_stock >= 2 and rng.random() < 0.6:
                qty = min(intra_stock, rng.randint(1, 3))
                items.append((INTRA_PRODUCT, qty))
                intra_stock -= qty
            if rng.random() < 0.4:
                items.append((rng.choice(services), 1))
            if not items:
                continue
            move = sell(company, customer, day_in(month), items)
            open_sales.append(move)
        if company == A:
            for _i in range(3):
                invoice(A, "out_invoice", rng.choice(customers), day_in(month),
                        [(rng.choice(services), rng.randint(1, 3), rng.choice(services).list_price)])
        # Replenish goods sold
        sold = [(g, -stock[company.id][g.id] + rng.randint(5, 12)) for g in goods
                if stock[company.id][g.id] < 5 and not (company == S and g == INTRA_PRODUCT) and company != A]
        for chunk in range(0, len(sold), 4):
            bill = buy_goods(company, rng.choice(vendors), day_in(month, 1, 8), sold[chunk:chunk + 4])
            pay(bill, day_in(month, 20, 28), rng.choice([1.0, 1.0, 0.5]))
        # Bought services
        for name in ("Vận chuyển giao hàng", "Quảng cáo trực tuyến", "Điện, nước, internet", "Văn phòng phẩm"):
            if company == A and name.startswith(("Vận", "Quảng")):
                continue
            bill = invoice(company, "in_invoice", rng.choice(vendors), day_in(month),
                           [(bought[name], 1, round(bought[name].standard_price * rng.uniform(0.7, 1.4), -3))])
            pay(bill, day_in(month, 25, 28))
        # Payroll: gross wage, insurance 21.5% employer / 10.5% employee, PIT ~5%
        selling = 0 if company == A else 0.35
        je(company, end, "Lương tháng %s" % month.strftime("%m/%Y"),
           [("6411", wage * selling * M), ("6421", wage * (1 - selling) * M), ("3341", -wage * M, employees)])
        je(company, end, "Trích BHXH, BHYT, BHTN tháng %s" % month.strftime("%m/%Y"),
           [("6421", wage * 0.215 * M), ("3383", -wage * 0.175 * M, social), ("3384", -wage * 0.03 * M, social),
            ("3386", -wage * 0.01 * M, social)])
        je(company, end, "Khấu trừ lương: BH, thuế TNCN", [("3341", wage * 0.155 * M, employees),
           ("3383", -wage * 0.08 * M, social), ("3384", -wage * 0.015 * M, social), ("3386", -wage * 0.01 * M, social),
           ("33351", -wage * 0.05 * M, tax_office)])
        next5 = month + relativedelta(months=1, days=4)
        if next5 <= CUTOFF:
            je(company, next5, "Trả lương tháng %s" % month.strftime("%m/%Y"),
               [("3341", wage * 0.845 * M, employees), ("1120", -wage * 0.845 * M)])
            je(company, next5, "Nộp bảo hiểm", [("3383", wage * 0.255 * M, social), ("3384", wage * 0.045 * M, social),
                                               ("3386", wage * 0.02 * M, social), ("1120", -wage * 0.32 * M)])
        # Rent amortisation
        rent = {P.id: 100, S.id: 50, A.id: 30}[company.id]
        je(company, end, "Phân bổ tiền thuê văn phòng", [("6427", rent * M), ("2421", -rent * M)])
        # Cost of goods sold
        cogs = cogs_month.pop((company.id, month), 0)
        je(company, end, "Giá vốn hàng bán tháng %s" % month.strftime("%m/%Y"), [("6320", cogs), ("1560", -cogs)])

    # Intra-group: P sells servers to S, S books the purchase
    qty = rng.randint(2, 5)
    price = SERVER_PRICE
    day = day_in(month, 3, 10)
    sale = invoice(P, "out_invoice", S.partner_id, day, [(INTRA_PRODUCT, qty, price)], "Bán cho công ty con")
    stock[P.id][INTRA_PRODUCT.id] -= qty
    je(P, month_end(month), "Giá vốn bán nội bộ", [("6320", qty * INTRA_PRODUCT.standard_price), ("1560", -qty * INTRA_PRODUCT.standard_price)])
    purchase = invoice(S, "in_invoice", P.partner_id, day, [(INTRA_PRODUCT, qty, price)], sale.name)
    stock[S.id][INTRA_PRODUCT.id] += qty
    intra_stock += qty
    if month + relativedelta(months=1) <= CUTOFF:
        pay_day = day + relativedelta(days=30)
        if pay_day <= CUTOFF:
            pay(purchase, pay_day)
            pay(sale, pay_day)
    # Bank loan interest
    if date(2025, 4, 1) < month_end(month):
        principal = 20_000 if month < date(2026, 4, 1) else 15_000
        je(P, month_end(month), "Lãi vay tháng %s" % month.strftime("%m/%Y"),
           [("6351", principal * M * 0.075 / 12), ("1120", -principal * M * 0.075 / 12)])

    # Collect customer invoices: most within ~45 days, some partially
    for move in list(open_sales):
        if move.invoice_date + relativedelta(days=45) <= month_end(month) and move.amount_residual:
            ratio = rng.choice([1.0, 1.0, 1.0, 0.6])
            pay(move, min(move.invoice_date + relativedelta(days=rng.randint(15, 45)), CUTOFF), ratio)
            if ratio == 1.0 or rng.random() < 0.5:
                open_sales.remove(move)

    # Credit notes now and then
    if month.month % 3 == 0:
        original = rng.choice([m for m in open_sales if m.company_id == S] or open_sales)
        line = original.invoice_line_ids.filtered(lambda l: l.product_id != INTRA_PRODUCT)[:1]
        if not line:
            continue
        refund = invoice(original.company_id, "out_refund", original.partner_id, month_end(month),
                         [(line.product_id, 1, line.price_unit)], f"Hàng bán bị trả lại - {original.name}")
        if line.product_id.type == "consu":
            je(original.company_id, month_end(month), "Nhập lại kho hàng bị trả lại",
               [("1560", unit_cost(original.company_id, line.product_id)), ("6320", -unit_cost(original.company_id, line.product_id))])

    # Customer advances and supplier prepayments (credit / debit balances on 131 / 331)
    if month.month in (6, 11):
        free_payment(P, customers[month.month], day_in(month), 500 * M, True, "Khách hàng ứng trước hợp đồng")
        free_payment(S, vendors[month.month % 12], day_in(month), 300 * M, False, "Ứng trước cho nhà cung cấp")

    # VAT: offset input against output, pay the rest on the 20th of the next month
    for company in COMPANIES:
        lines = cenv(company)["account.move.line"]._read_group(
            [("company_id", "=", company.id), ("parent_state", "=", "posted"), ("date", "<=", month_end(month)),
             ("account_id", "in", (acc(company, "33311") | acc(company, "1331")).ids)],
            ["account_id"], ["balance:sum"])
        balances = {account.id: balance for account, balance in lines}
        output = -balances.get(acc(company, "33311").id, 0)
        input_vat = balances.get(acc(company, "1331").id, 0)
        offset = min(output, input_vat)
        je(company, month_end(month), "Khấu trừ thuế GTGT", [("33311", offset), ("1331", -offset)])
        due = output - offset
        pay_day = month + relativedelta(months=1, day=20)
        if due > 0 and pay_day <= CUTOFF:
            je(company, pay_day, "Nộp thuế GTGT", [("33311", due, tax_office), ("1120", -due)])

    # Quarterly provisional CIT at 20%
    if month.month in (3, 6, 9, 12):
        for company in COMPANIES:
            quarter_start = month - relativedelta(months=2)
            [(balance,)] = cenv(company)["account.move.line"]._read_group(
                [("company_id", "=", company.id), ("parent_state", "=", "posted"), ("date", ">=", quarter_start),
                 ("date", "<=", month_end(month)), ("account_id.account_type", "in",
                 ("income", "income_other", "expense", "expense_direct_cost", "expense_depreciation"))],
                [], ["balance:sum"])
            profit = -(balance or 0)
            if profit > 0:
                cit = round(profit * 0.2, -3)
                je(company, month_end(month), "Tạm tính thuế TNDN quý", [("82111", cit), ("33341", -cit, tax_office)])
                pay_day = month + relativedelta(months=1, day=28)
                if pay_day <= CUTOFF:
                    je(company, pay_day, "Nộp thuế TNDN tạm tính", [("33341", cit, tax_office), ("1120", -cit)])

    if month == date(2025, 12, 1):
        intra_stock_2025 = intra_stock

    # Year end 2025: doubtful debt provision, then close P&L to 911 and 4212
    if month == date(2025, 12, 1):
        for company in (P, S):
            je(company, date(2025, 12, 31), "Trích lập dự phòng phải thu khó đòi", [("6426", 80 * M), ("22931", -80 * M)])
        for company in COMPANIES:
            lines = cenv(company)["account.move.line"]._read_group(
                [("company_id", "=", company.id), ("parent_state", "=", "posted"), ("date", ">=", date(2025, 1, 1)),
                 ("date", "<=", date(2025, 12, 31))], ["account_id"], ["balance:sum"])
            items, result = [], 0.0
            for account, balance in lines:
                code = account.with_company(company).code
                if code[:1] in "5678" and round(balance):
                    items.append((code, -balance))
                    result += balance
            je(company, date(2025, 12, 31), "Kết chuyển doanh thu, chi phí xác định KQKD", items + [("9110", result)])
            je(company, date(2025, 12, 31), "Kết chuyển lợi nhuận sau thuế", [("9110", -result), ("4212", result)])
            je(company, date(2026, 1, 1), "Kết chuyển LNST năm trước sang lũy kế", [("4212", -result), ("4211", result)])

# S distributes a dividend out of 2025 profit: 80% to P, 20% to the minority
je(S, date(2026, 4, 15), "Chia cổ tức năm 2025", [("4211", 2_000 * M), ("3320", -1_600 * M, P.partner_id), ("3320", -400 * M, minority)])
je(P, date(2026, 4, 15), "Cổ tức được chia từ công ty con", [("13881", 1_600 * M, S.partner_id), ("5150", -1_600 * M, S.partner_id)])
je(S, date(2026, 5, 10), "Trả cổ tức", [("3320", 1_600 * M, P.partner_id), ("3320", 400 * M, minority), ("1120", -2_000 * M)])
je(P, date(2026, 5, 10), "Nhận cổ tức", [("1120", 1_600 * M), ("13881", -1_600 * M, S.partner_id)])

# ---------------------------------------------------------------- consolidation group
server_price = SERVER_PRICE
margin = (server_price - INTRA_PRODUCT.standard_price) / server_price * 100
group = env["vn.consolidation.group"].create({
    "name": "Tập đoàn Tricasia Demo", "parent_company_id": P.id,
    "member_ids": [
        (0, 0, {"company_id": S.id, "method": "full", "ownership_pct": 80, "acquisition_date": date(2025, 3, 31)}),
        (0, 0, {"company_id": A.id, "method": "equity", "ownership_pct": 30, "acquisition_date": date(2025, 1, 2)}),
    ],
})
group.member_ids.filtered(lambda m: m.method == "full").action_take_snapshot()
print("INTRA_STOCK_LEFT", intra_stock, "MARGIN", margin)
for day, qty in ((date(2025, 12, 31), intra_stock_2025), (CUTOFF, intra_stock)):
    env["vn.consolidation.unrealized"].create({
        "group_id": group.id, "date": day, "seller_company_id": P.id, "buyer_company_id": S.id,
        "kind": "inventory", "goods_value": qty * server_price, "margin_pct": margin,
        "amount": qty * (server_price - INTRA_PRODUCT.standard_price),
    })
env.cr.commit()
print("STATS", dict(stats))
print("MOVES", env["account.move"].search_count([("state", "=", "posted")]))
