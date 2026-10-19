"""Build i18n/vi.po of the Vietnamese accounting modules from their .pot files.

The .pot files are exported by Odoo (see below). Report captions are
translated from ``report_terms.py``, every other term from ``ui_terms_vi.py``.

    # 1. export the templates from a database where the modules are installed
    docker compose run --rm -T --entrypoint sh odoo -c '... odoo i18n export -c <conf> -d <db> \\
        l10n_vn_financial_statements l10n_vn_consolidation vietqr_tax_lookup'
    # 2. build the Vietnamese files (fails if a term has no translation)
    python tools/vn_accounting/build_i18n.py
    python tools/vn_accounting/build_i18n.py --missing     # only list untranslated terms
"""

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from report_terms import vietnamese_by_english  # noqa: E402
from ui_terms_vi import UI_TERMS  # noqa: E402
from ifrs_terms_vi import IFRS_TERMS  # noqa: E402

MODULES = ["vietqr_tax_lookup", "l10n_vn_financial_statements", "l10n_vn_consolidation", "l10n_vn_ifrs"]


def parse_po(text):
    """[(comment lines, msgid, msgstr)] — header entry included (empty msgid)."""
    entries = []
    for block in text.strip().split("\n\n"):
        comments, msgid, msgstr, current = [], [], [], None
        for line in block.splitlines():
            if line.startswith("#"):
                comments.append(line)
            elif line.startswith("msgid "):
                current = msgid
                current.append(ast.literal_eval(line[6:]))
            elif line.startswith("msgstr "):
                current = msgstr
                current.append(ast.literal_eval(line[7:]))
            elif line.startswith('"') and current is not None:
                current.append(ast.literal_eval(line))
        entries.append((comments, "".join(msgid), "".join(msgstr)))
    return entries


def po_string(text):
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    if "\\n" in escaped and len(escaped) > 70:
        parts = escaped.split("\\n")
        lines = [p + "\\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
        return '""\n' + "\n".join(f'"{line}"' for line in lines)
    return f'"{escaped}"'


HEADER = """# Translation of Odoo Server.
# This file contains the translation of the following modules:
# \t* {module}
#
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 19.0\\n"
"Report-Msgid-Bugs-To: \\n"
"Language: vi\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: \\n"
"Plural-Forms: nplurals=1; plural=0;\\n"
"""


def main():
    terms = dict(vietnamese_by_english())
    for en, vi in list(UI_TERMS.items()) + list(IFRS_TERMS.items()):
        if en in terms and terms[en] != vi:
            raise SystemExit(f"Conflicting translations for {en!r}")
        terms[en] = vi
    missing = {}
    for module in MODULES:
        pot = ROOT / "my_modules" / module / "i18n" / f"{module}.pot"
        entries = parse_po(pot.read_text(encoding="utf-8"))
        out = [HEADER.format(module=module)]
        for comments, msgid, _msgstr in entries:
            if not msgid:
                continue
            translation = terms.get(msgid)
            if translation is None:
                missing.setdefault(module, []).append(msgid)
                translation = ""
            out.append("\n".join(comments + [f"msgid {po_string(msgid)}", f"msgstr {po_string(translation)}"]) + "\n")
        if "--missing" not in sys.argv:
            (pot.parent / "vi.po").write_text("\n".join(out), encoding="utf-8", newline="\n")
    for module, msgids in missing.items():
        print(f"{module}: {len(msgids)} untranslated")
        for msgid in msgids:
            print("   ", repr(msgid))
    if missing and "--missing" not in sys.argv:
        raise SystemExit("Some terms have no Vietnamese translation.")


if __name__ == "__main__":
    main()
