"""Build docs/tt99/TT99_Documentation.{html,pdf}.

Fills the source HTML with the formula appendix (read from the modules' data
XML) and the list of automated tests, then prints it to PDF with Chrome once
the Mermaid diagrams are drawn (tools/tt99/print_pdf.mjs, needs node >= 22).

Usage, from the repo root:  python tools/tt99/build_docs.py
"""

import ast
import datetime
import html
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "my_modules"
DOCS = ROOT / "docs" / "tt99"
SOURCE = DOCS / "src" / "TT99_Documentation.src.html"
OUTPUT_HTML = DOCS / "TT99_Documentation.html"
OUTPUT_PDF = DOCS / "TT99_Documentation.pdf"

REPORT_FILES = [
    MODULES / "l10n_vn_tt99_reports" / "data" / "vn_report_b01.xml",
    MODULES / "l10n_vn_tt99_reports" / "data" / "vn_report_b02.xml",
    MODULES / "l10n_vn_tt99_reports" / "data" / "vn_report_b03.xml",
    MODULES / "l10n_vn_tt99_consolidation" / "data" / "vn_report_hn.xml",
]
TEST_DIRS = {
    "l10n_vn_tt99_reports": MODULES / "l10n_vn_tt99_reports" / "tests",
    "l10n_vn_tt99_consolidation": MODULES / "l10n_vn_tt99_consolidation" / "tests",
    "vietqr_tax_lookup": MODULES / "vietqr_tax_lookup" / "tests",
}


def esc(text):
    return html.escape(text or "")


def appendix():
    reports, lines = {}, {}
    for path in REPORT_FILES:
        for record in ET.parse(path).getroot().iter("record"):
            fields = {f.get("name"): f for f in record.iter("field")}
            if record.get("model") == "vn.report":
                reports[record.get("id")] = {name: (f.text or "") for name, f in fields.items()}
                lines[record.get("id")] = []
            elif record.get("model") == "vn.report.line":
                lines[fields["report_id"].get("ref")].append(
                    {
                        "code": fields["code"].text or "",
                        "name": fields["name"].text or "",
                        "formula": fields["formula"].text or "",
                        "level": int(fields["level"].text or 2),
                        "bold": fields["bold"].get("eval") == "True",
                    }
                )
    blocks = []
    for xmlid, report in reports.items():
        rows = []
        for line in lines[xmlid]:
            indent = "&nbsp;" * 3 * max(line["level"] - 1, 0)
            name = f"<b>{esc(line['name'])}</b>" if line["bold"] else esc(line["name"])
            code = "" if line["code"].isalpha() else esc(line["code"])
            formula = f"<code>{esc(line['formula'])}</code>" if line["formula"] else "<i>(nhập tay / để trống)</i>"
            rows.append(f"<tr><td>{code}</td><td>{indent}{name}</td><td>{formula}</td></tr>")
        check = report.get("check_expression")
        blocks.append(
            f"<h3>{esc(report['name'])}</h3>"
            f"<p class='small'>Mã <code>{esc(report['code'])}</code> — loại <code>{esc(report['kind'])}</code>"
            + (f" — kiểm tra <code>{esc(check)}</code>" if check else "")
            + "</p>"
            "<table class='appendix'><tr><th style='width:8%'>Mã số</th><th style='width:46%'>Chỉ tiêu</th>"
            "<th>Công thức</th></tr>" + "".join(rows) + "</table>"
        )
    return "\n".join(blocks)


def test_table():
    rows = []
    for module, folder in TEST_DIRS.items():
        for path in sorted(folder.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    doc = (ast.get_docstring(node) or "").split("\n")[0]
                    rows.append(
                        f"<tr><td><code>{module}</code></td><td><code>{node.name}</code></td><td>{esc(doc)}</td></tr>"
                    )
    return (
        f"<p>{len(rows)} test, chạy bằng lệnh ở mục 12.</p>"
        "<table><tr><th style='width:26%'>Module</th><th style='width:40%'>Test</th><th>Ghi chú</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def main():
    source = SOURCE.read_text(encoding="utf-8")
    page = (
        source.replace("{{BUILD_DATE}}", datetime.date.today().strftime("%d/%m/%Y"))
        .replace("{{APPENDIX}}", appendix())
        .replace("{{TEST_TABLE}}", test_table())
    )
    OUTPUT_HTML.write_text(page, encoding="utf-8", newline="\n")
    print("HTML", OUTPUT_HTML)
    if "--html-only" in sys.argv:
        return
    script = Path(__file__).with_name("print_pdf.mjs")
    subprocess.run(["node", str(script), str(OUTPUT_HTML), str(OUTPUT_PDF)], check=True)
    print("PDF", OUTPUT_PDF)


if __name__ == "__main__":
    main()
