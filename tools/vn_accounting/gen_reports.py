"""Generate the report definition XML files (Circular 99/2025).

Usage (repo root): python tools/vn_accounting/gen_reports.py docs/vn_accounting/research/circular99_b01_b02.csv my_modules/l10n_vn_financial_statements my_modules/l10n_vn_consolidation
Captions come from the research CSV (gazette text); formulas are mapped here
onto the account codes of Odoo 19's l10n_vn chart.
"""

import csv
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_terms import english  # noqa: E402

# Report fields written in English; their Vietnamese text goes to i18n/vi.po.
TRANSLATED_FIELDS = {"name", "form_code", "form_note", "title", "subtitle", "check_message"}

csv_path, reports_dir, conso_dir = sys.argv[1:4]
rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))


def captions(report):
    return [(r["code"], r["caption_vi"].strip()) for r in rows if r["report"] == report]


# ---------------------------------------------------------------- B01-DN
SHORT_OTHER_RECEIVABLE = "13881, 1411, 2441, 3341, 33811, 33821, 33831, 33841, 33861, 33881, 3441, 332"
LONG_OTHER_RECEIVABLE = "13882, 1412, 2442, 3342, 33812, 33822, 33832, 33842, 33862, 33882, 3442"
TAX_SHORT = "33311, 33312, 33321, 33331, 33341, 33351, 33361, 33371, 33381, 33382, 33391"
TAX_LONG = "33322, 33332, 33342, 33352, 33362, 33372, 33392"

B01 = {
    "100": "[110] + [120] + [130] + [140] + [150] + [160]",
    "110": "[111] + [112]",
    "111": "BAL(111, 112, 113)",
    "112": "BAL(12811, 12881)",
    "120": "[121] + [122] + [123] + [124] + [125] + [126]",
    "121": "BAL(121)",
    "122": "BAL(2291)",
    "123": "BAL(12812, 12822, 12831, 12882)",
    "124": "",
    "125": "BAL(22811)",
    "126": "BAL(22921, 22922)",
    "130": "[131] + [132] + [133] + [134] + [135] + [136] + [137]",
    "131": "PDR(1311)",
    "132": "PDR(3311)",
    "133": "BAL(13621, 13631, 13681)",
    "134": "PDR(337)",
    "135": f"PDR({SHORT_OTHER_RECEIVABLE}) + DR(3351)",
    "136": "BAL(22931)",
    "137": "PDR(13811, 13812)",
    "140": "[141] + [142]",
    "141": "BAL(151, 152, 1531, 1541, 155, 156, 157, 158)",
    "142": "BAL(22941)",
    "150": "[151] + [152] + [153]",
    "151": "BAL(21521)",
    "152": "BAL(21531)",
    "153": "BAL(22951)",
    "160": "[161] + [162] + [163] + [164] + [165]",
    "161": "BAL(2421)",
    "162": "BAL(133)",
    "163": "PDR(13831, 13832) + DR(333)",
    "164": "DR(171)",
    "165": "BAL(22881)",
    "200": "[210] + [220] + [230] + [240] + [250] + [260] + [270]",
    "210": "[211] + [212] + [213] + [214] + [215] + [216]",
    "211": "PDR(1312)",
    "212": "PDR(3312)",
    "213": "BAL(1361)",
    "214": "BAL(13622, 13632, 13682)",
    "215": f"PDR({LONG_OTHER_RECEIVABLE}) + DR(3352)",
    "216": "BAL(22932)",
    "220": "[221] + [224] + [227]",
    "221": "[222] + [223]",
    "222": "BAL(211)",
    "223": "BAL(2141)",
    "224": "[225] + [226]",
    "225": "BAL(212)",
    "226": "BAL(2142)",
    "227": "[228] + [229]",
    "228": "BAL(213)",
    "229": "BAL(2143)",
    "230": "[231] + [236] + [237] + [238]",
    "231": "[232] + [233]",
    "232": "BAL(21511)",
    "233": "[234] + [235]",
    "234": "BAL(215121)",
    "235": "BAL(215122)",
    "236": "BAL(21522)",
    "237": "BAL(21532)",
    "238": "BAL(22952)",
    "240": "[241] + [242]",
    "241": "BAL(217)",
    "242": "BAL(2147)",
    "250": "[251] + [252]",
    "251": "BAL(1542, 22942)",
    "252": "BAL(241)",
    "260": "[261] + [262] + [263] + [264] + [265] + [266]",
    "261": "BAL(221)",
    "262": "BAL(222)",
    "263": "BAL(22812)",
    "264": "BAL(22923)",
    "265": "BAL(12813, 12823, 12832, 12883)",
    "266": "BAL(22924)",
    "270": "[271] + [272] + [273] + [274]",
    "271": "BAL(2422)",
    "272": "BAL(243)",
    "273": "BAL(1532, 22943)",
    "274": "BAL(22882)",
    "280": "[100] + [200]",
    "300": "[310] + [330]",
    "310": " + ".join(f"[{c}]" for c in range(311, 326)),
    "311": "PCR(3311)",
    "312": "PCR(1311)",
    "313": "PCR(332)",
    "314": f"CR({TAX_SHORT})",
    "315": "PCR(3341)",
    "316": "CR(3351)",
    "317": "NBAL(33621, 33631, 33681)",
    "318": "PCR(337)",
    "319": "NBAL(33871)",
    "320": "PCR(13811, 13812, 13831, 13881, 1411, 2441, 33811, 33821, 33831, 33841, 33861, 33881, 3441)",
    "321": "NBAL(34111, 34121, 34311)",
    "322": "NBAL(35211, 35221, 35231, 35251)",
    "323": "NBAL(353)",
    "324": "NBAL(357)",
    "325": "CR(171)",
    "330": " + ".join(f"[{c}]" for c in range(331, 345)),
    "331": "PCR(3312)",
    "332": "PCR(1312)",
    "333": f"CR({TAX_LONG})",
    "334": "CR(3352)",
    "335": "NBAL(3361)",
    "336": "NBAL(33622, 33632, 33682)",
    "337": "NBAL(33872)",
    "338": "PCR(13832, 13882, 1412, 2442, 3342, 33812, 33822, 33832, 33842, 33862, 33882, 3442)",
    "339": "NBAL(34112, 34122, 34312)",
    "340": "NBAL(3432)",
    "341": "NBAL(411121)",
    "342": "NBAL(347)",
    "343": "NBAL(35212, 35222, 35232, 35252)",
    "344": "NBAL(356)",
    "400": "[411] + [412] + [413] + [414] + [415] + [416] + [417] + [418] + [419] + [420]",
    "411": "[411a] + [411b]",
    "411a": "NBAL(41111)",
    "411b": "NBAL(411122)",
    "412": "NBAL(4112)",
    "413": "NBAL(4113)",
    "414": "NBAL(4118)",
    "415": "NBAL(419)",
    "416": "NBAL(412)",
    "417": "NBAL(413)",
    "418": "NBAL(414)",
    "419": "NBAL(418)",
    "420": "[420a] + [420b]",
    "420a": "NBAL(4211) + PL_PRIOR()",
    "420b": "NBAL(4212) + PL_CUR()",
    "440": "[300] + [400]",
}

# ---------------------------------------------------------------- B02-DN
B02 = {
    "01": "CT(511) - CT(5117)",
    "02": "DT(511) - DT(5117) + BAL(521)",
    "10": "[01] - [02]",
    "11": "BAL(632) - BAL(6327)",
    "20": "[10] - [11]",
    "21": "NBAL(5117) - BAL(6327)",
    "22": "NBAL(515)",
    "23": "BAL(635)",
    "24": "BAL(6351)",
    "25": "BAL(641)",
    "26": "BAL(642)",
    "30": "[20] + [21] + [22] - [23] - [25] - [26]",
    "31": "NBAL(711)",
    "32": "BAL(811)",
    "40": "[31] - [32]",
    "50": "[30] + [40]",
    "51": "BAL(8211)",
    "52": "BAL(8212)",
    "60": "[50] - [51] - [52]",
    "70": "",
    "71": "",
}

# ---------------------------------------------------------------- B03-DN
CASH_SET = "111, 112, 113, 12811, 12881"
INVESTING = {
    "21": "CASHD(211, 212, 213, 215, 217, 241)",
    "22": "CASHC(211, 212, 213, 215, 217, 241, 711, 5117)",
    "23": "CASHD(1281, 1282, 1283, 1288, 171)",
    "24": "CASHC(1281, 1282, 1283, 1288, 171)",
    "25": "CASHD(221, 222, 2281)",
    "26": "CASHC(221, 222, 2281)",
    "27": "CASHC(515)",
    "30": "[21] + [22] + [23] + [24] + [25] + [26] + [27]",
    "31": "CASHC(411)",
    "32": "CASHD(411, 419)",
    "33": "CASHC(341, 343)",
    "34": "CASHD(3411, 343)",
    "35": "CASHD(3412)",
    "36": "CASHD(332, 421)",
    "40": "[31] + [32] + [33] + [34] + [35] + [36]",
    "50": "[20] + [30] + [40]",
    "60": f"OPEN({CASH_SET})",
    "61": "CASH(413)",
    "70": "[50] + [60] + [61]",
}
B03_DIRECT_CAPTIONS = [
    ("I", "I. Lưu chuyển tiền từ hoạt động kinh doanh"),
    ("01", "1. Tiền thu từ bán hàng, cung cấp dịch vụ và doanh thu khác"),
    ("02", "2. Tiền chi trả cho người cung cấp hàng hóa và dịch vụ"),
    ("03", "3. Tiền chi trả cho người lao động"),
    ("04", "4. Chi phí đi vay đã trả"),
    ("05", "5. Thuế thu nhập doanh nghiệp đã nộp"),
    ("06", "6. Tiền thu khác từ hoạt động kinh doanh"),
    ("07", "7. Tiền chi khác cho hoạt động kinh doanh"),
    ("20", "Lưu chuyển tiền thuần từ hoạt động kinh doanh"),
    ("II", "II. Lưu chuyển tiền từ hoạt động đầu tư"),
    ("21", "1. Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác"),
    ("22", "2. Tiền thu từ thanh lý, nhượng bán TSCĐ và các tài sản dài hạn khác"),
    ("23", "3. Tiền chi cho vay, mua các công cụ nợ của đơn vị khác"),
    ("24", "4. Tiền thu hồi cho vay, bán lại các công cụ nợ của đơn vị khác"),
    ("25", "5. Tiền chi đầu tư góp vốn vào đơn vị khác"),
    ("26", "6. Tiền thu hồi đầu tư góp vốn vào đơn vị khác"),
    ("27", "7. Tiền thu lãi cho vay, cổ tức và lợi nhuận được chia"),
    ("30", "Lưu chuyển tiền thuần từ hoạt động đầu tư"),
    ("III", "III. Lưu chuyển tiền từ hoạt động tài chính"),
    ("31", "1. Tiền thu từ phát hành cổ phiếu, nhận vốn góp của chủ sở hữu"),
    ("32", "2. Tiền trả lại vốn góp cho các chủ sở hữu, mua lại cổ phiếu đã phát hành"),
    ("33", "3. Tiền thu từ đi vay"),
    ("34", "4. Tiền trả nợ gốc vay"),
    ("35", "5. Tiền trả nợ gốc thuê tài chính"),
    ("36", "6. Cổ tức, lợi nhuận đã trả cho chủ sở hữu"),
    ("40", "Lưu chuyển tiền thuần từ hoạt động tài chính"),
    ("50", "Lưu chuyển tiền thuần trong kỳ (50 = 20 + 30 + 40)"),
    ("60", "Tiền và tương đương tiền đầu kỳ"),
    ("61", "Ảnh hưởng của thay đổi tỷ giá hối đoái quy đổi ngoại tệ"),
    ("70", "Tiền và tương đương tiền cuối kỳ (70 = 50 + 60 + 61)"),
]
B03_DIRECT = {
    "I": "",
    "01": "CASH(131, 511, 521, 3331, 3387) - CASH(5117)",
    "02": "CASH(331, 151, 152, 153, 154, 155, 156, 157, 158, 133, 242, 621, 623, 627, 641, 642)",
    "03": "CASH(334)",
    "04": "CASH(6351)",
    "05": "CASH(3334)",
    "06": "CASH_REST_IN()",
    "07": "CASH_REST_OUT()",
    "20": "[01] + [02] + [03] + [04] + [05] + [06] + [07]",
    "II": "",
    "III": "",
    **INVESTING,
}
B03_INDIRECT = {
    "01": "NBAL(511, 515, 521, 711) - BAL(632, 635, 641, 642, 811)",
    "02": "CT(214, 215122)",
    "03": "-CHG(229, 352)",
    "04": "",
    "05": "-NBAL(515, 5117) + BAL(6327)",
    "06": "BAL(6351)",
    "07": "",
    "08": "[01] + [02] + [03] + [04] + [05] + [06] + [07]",
    "09": "-CHG(131, 133, 136, 138, 141, 244)",
    "10": "-CHG(151, 152, 153, 154, 155, 156, 157, 158)",
    "11": "-CHG(331, 3331, 3332, 3333, 3335, 3336, 3337, 3338, 3339, 334, 335, 336, 337, 338, 344)",
    "12": "-CHG(242)",
    "13": "-CHG(121)",
    "14": "CASH(6351)",
    "15": "CASH(3334)",
    "16": "",
    "17": "",
    "20": "[08] + [09] + [10] + [11] + [12] + [13] + [14] + [15] + [16] + [17]",
    **INVESTING,
}
B03_INDIRECT_SECTIONS = {
    "01": ("I", "I. Lưu chuyển tiền từ hoạt động kinh doanh"),
    "21": ("II", "II. Lưu chuyển tiền từ hoạt động đầu tư"),
    "31": ("III", "III. Lưu chuyển tiền từ hoạt động tài chính"),
}

# ---------------------------------------------------------------- levels
TOP = {"100", "200", "280", "300", "400", "440"}
TOTALS = {"10", "20", "30", "40", "50", "60", "70", "08"}


def b01_style(code, caption):
    if code in TOP:
        return 0, True
    if re.match(r"^[IVX]+\.", caption):
        return 1, True
    if caption.startswith("-") or re.match(r"^[a-z]\)", caption):
        return 3, False
    return 2, False


def flow_style(code, caption):
    if code in ("I", "II", "III"):
        return 1, True
    if code in TOTALS or caption.startswith("Lưu chuyển") or caption.startswith("Tiền và"):
        return 1, True
    if caption.startswith("-"):
        return 3, False
    return 2, False


def xml_lines(prefix, report_ref, items):
    out = []
    for seq, (code, caption, formula, level, bold) in enumerate(items, start=1):
        xmlid = f"{prefix}_{code}".replace(".", "_")
        out.append(
            f'    <record id="{xmlid}" model="vn.report.line">\n'
            f'        <field name="report_id" ref="{report_ref}"/>\n'
            f'        <field name="sequence">{seq * 10}</field>\n'
            f'        <field name="code">{escape(code)}</field>\n'
            f'        <field name="name">{escape(english(caption))}</field>\n'
            f'        <field name="formula">{escape(formula)}</field>\n'
            f'        <field name="level">{level}</field>\n'
            f'        <field name="bold" eval="{bold}"/>\n'
            f"    </record>"
        )
    return out


def report_record(xmlid, fields):
    body = "\n".join(
        f'        <field name="{k}" eval="{v}"/>'
        if isinstance(v, bool)
        else f'        <field name="{k}">{escape(english(v) if k in TRANSLATED_FIELDS else str(v))}</field>'
        for k, v in fields.items()
    )
    return f'    <record id="{xmlid}" model="vn.report">\n{body}\n    </record>'


def write(path, blocks):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n')
        f.write("\n\n".join(blocks))
        f.write("\n</odoo>\n")


def build(caption_list, formulas, style, overrides=None, extra=None, drop=()):
    """Return [(code, caption, formula, level, bold)] in order."""
    overrides = overrides or {}
    extra = extra or {}
    items = []
    for code, caption in caption_list:
        if code in drop:
            continue
        formula = overrides.get(code, formulas.get(code))
        if formula is None:
            raise SystemExit(f"no formula for {code}")
        level, bold = style(code, caption)
        items.append((code, caption, formula, level, bold))
        for e_code, e_caption, e_formula in extra.get(code, []):
            level, bold = style(e_code, e_caption)
            items.append((e_code, e_caption, e_formula, level, bold))
    return items


# Clean B01 captions: research captions for 231/233 already final.
b01_captions = captions("B01-DN")
b02_captions = captions("B02-DN")
b03i_captions = []
for code, caption in captions("B03-DN-indirect"):
    if code in B03_INDIRECT_SECTIONS:
        b03i_captions.append(B03_INDIRECT_SECTIONS[code])
    b03i_captions.append((code, caption))
B03_INDIRECT.update({"I": "", "II": "", "III": ""})

missing = [c for c, _ in b01_captions if c not in B01]
assert not missing, missing

# ------------------------------------------------------------- standalone
b01 = build(b01_captions, B01, b01_style)
b02 = build(b02_captions, B02, lambda c, n: ((1, True) if c in TOTALS else (2, False)))
b03d = build(B03_DIRECT_CAPTIONS, B03_DIRECT, flow_style)
b03i = build(b03i_captions, B03_INDIRECT, flow_style)

common = {"form_note": "(Kèm theo Thông tư số 99/2025/TT-BTC ngày 27 tháng 10 năm 2025 của Bộ trưởng Bộ Tài chính)"}
write(
    f"{reports_dir}/data/vn_report_b01.xml",
    [
        report_record(
            "report_b01",
            {
                "name": "B01-DN Báo cáo tình hình tài chính",
                "code": "B01-DN",
                "sequence": 10,
                "kind": "position",
                "form_code": "Mẫu số B 01 - DN",
                **common,
                "title": "BÁO CÁO TÌNH HÌNH TÀI CHÍNH",
                "subtitle": "(Áp dụng cho doanh nghiệp đáp ứng giả định hoạt động liên tục)",
                "check_expression": "[280] - [440]",
                "check_message": "Tổng tài sản (280) không bằng tổng nguồn vốn (440)",
            },
        )
    ]
    + xml_lines("b01", "report_b01", b01),
)
write(
    f"{reports_dir}/data/vn_report_b02.xml",
    [
        report_record(
            "report_b02",
            {
                "name": "B02-DN Báo cáo kết quả hoạt động kinh doanh",
                "code": "B02-DN",
                "sequence": 20,
                "kind": "period",
                "form_code": "Mẫu số B 02 - DN",
                **common,
                "title": "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH",
            },
        )
    ]
    + xml_lines("b02", "report_b02", b02),
)
write(
    f"{reports_dir}/data/vn_report_b03.xml",
    [
        report_record(
            "report_b03_direct",
            {
                "name": "B03-DN Báo cáo lưu chuyển tiền tệ (trực tiếp)",
                "code": "B03-DN",
                "sequence": 30,
                "kind": "cashflow",
                "form_code": "Mẫu số B 03 - DN",
                **common,
                "title": "BÁO CÁO LƯU CHUYỂN TIỀN TỆ",
                "subtitle": "(Theo phương pháp trực tiếp)",
                "check_expression": f"[70] - CLOSE({CASH_SET})",
                "check_message": "Tiền cuối kỳ (70) không khớp số dư tiền và tương đương tiền trên sổ",
            },
        )
    ]
    + xml_lines("b03d", "report_b03_direct", b03d)
    + [
        report_record(
            "report_b03_indirect",
            {
                "name": "B03-DN Báo cáo lưu chuyển tiền tệ (gián tiếp)",
                "code": "B03-DN-GT",
                "sequence": 31,
                "kind": "cashflow",
                "form_code": "Mẫu số B 03 - DN",
                **common,
                "title": "BÁO CÁO LƯU CHUYỂN TIỀN TỆ",
                "subtitle": "(Theo phương pháp gián tiếp)",
                "check_expression": f"[70] - CLOSE({CASH_SET})",
                "check_message": "Phương pháp gián tiếp: các dòng điều chỉnh là ước tính, tiền cuối kỳ (70) chưa khớp sổ — cần rà soát các chỉ tiêu 04, 07, 16, 17",
            },
        )
    ]
    + xml_lines("b03i", "report_b03_indirect", b03i),
)

# ------------------------------------------------------------- consolidated
# TT202 as amended by TT43/2026: no 133, 213, 214, 317, 335, 336 on the
# consolidated form; adds 279 goodwill, 429 NCI; B02 adds 27, 61, 62.
B01_HN = dict(B01)
B01_HN.update(
    {
        "130": "[131] + [132] + [134] + [135] + [136] + [137]",
        "135": B01["135"] + " + BAL(13621, 13631, 13681)",
        "210": "[211] + [212] + [215] + [216]",
        "215": B01["215"] + " + BAL(1361, 13622, 13632, 13682)",
        "270": "[271] + [272] + [273] + [274] + [279]",
        "310": " + ".join(f"[{c}]" for c in range(311, 326) if c != 317),
        "320": B01["320"] + " + NBAL(33621, 33631, 33681)",
        "330": " + ".join(f"[{c}]" for c in range(331, 345) if c not in (335, 336)),
        "338": B01["338"] + " + NBAL(3361, 33622, 33632, 33682)",
        "400": B01["400"] + " + [429]",
    }
)
B01_HN["420a"] = 'NBAL(4211, "HN_PREACQ") + PL_PRIOR()'
b01_hn = build(
    b01_captions,
    B01_HN,
    b01_style,
    drop={"133", "213", "214", "317", "335", "336"},
    extra={
        "274": [("279", "5. Lợi thế thương mại", 'BAL("HN_GW")')],
        "420b": [("429", "11. Lợi ích cổ đông không kiểm soát", 'NBAL("HN_NCI")')],
    },
)
B02_HN = dict(B02)
B02_HN.update(
    {
        "30": "[20] + [21] + [22] - [23] - [25] - [26] + [27]",
        "61": "[60] - [62]",
        "62": 'BAL("HN_PLNCI")',
    }
)
b02_hn = build(
    b02_captions,
    B02_HN,
    lambda c, n: ((1, True) if c in TOTALS else (2, False)),
    extra={
        "26": [("27", "11. Phần lãi hoặc lỗ trong công ty liên doanh, liên kết", 'NBAL("HN_EQPL")')],
        "60": [
            ("61", "- Lợi nhuận sau thuế của công ty mẹ", "[60] - [62]"),
            ("62", "- Lợi nhuận sau thuế của cổ đông không kiểm soát", 'BAL("HN_PLNCI")'),
        ],
    },
)
hn_note = "(Ban hành theo Thông tư số 202/2014/TT-BTC, sửa đổi bởi Thông tư số 43/2026/TT-BTC; mẫu theo Thông tư số 99/2025/TT-BTC)"
write(
    f"{conso_dir}/data/vn_report_hn.xml",
    [
        report_record(
            "report_b01_hn",
            {
                "name": "B01-DN/HN Báo cáo tình hình tài chính hợp nhất",
                "code": "B01-DN/HN",
                "sequence": 50,
                "kind": "position",
                "consolidated": True,
                "form_code": "Mẫu số B 01 - DN/HN",
                "form_note": hn_note,
                "title": "BÁO CÁO TÌNH HÌNH TÀI CHÍNH HỢP NHẤT",
                "check_expression": "[280] - [440]",
                "check_message": "Tổng tài sản (280) không bằng tổng nguồn vốn (440)",
            },
        )
    ]
    + xml_lines("b01hn", "report_b01_hn", b01_hn)
    + [
        report_record(
            "report_b02_hn",
            {
                "name": "B02-DN/HN Báo cáo kết quả hoạt động kinh doanh hợp nhất",
                "code": "B02-DN/HN",
                "sequence": 60,
                "kind": "period",
                "consolidated": True,
                "form_code": "Mẫu số B 02 - DN/HN",
                "form_note": hn_note,
                "title": "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH HỢP NHẤT",
            },
        )
    ]
    + xml_lines("b02hn", "report_b02_hn", b02_hn),
)
print("B01", len(b01), "B02", len(b02), "B03d", len(b03d), "B03i", len(b03i), "B01HN", len(b01_hn), "B02HN", len(b02_hn))
