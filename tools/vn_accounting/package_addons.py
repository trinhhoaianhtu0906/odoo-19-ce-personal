"""Package the Vietnamese accounting addons into a ZIP for deployment.

Usage (repo root): python tools/vn_accounting/package_addons.py
Writes dist/vn_accounting_addons_<version>_<date>.zip with the three addons,
DEPLOY.md and the documentation PDF. Git metadata and caches are left out.
"""

import ast
import datetime
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ["l10n_vn_financial_statements", "l10n_vn_consolidation", "l10n_vn_ifrs", "vietqr_tax_lookup"]
SKIP_DIRS = {".git", "__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def module_files(module):
    base = ROOT / "my_modules" / module
    for path in sorted(base.rglob("*")):
        if path.is_file() and not (set(path.relative_to(base).parts) & SKIP_DIRS) and path.suffix not in SKIP_SUFFIXES:
            if path.name == ".gitignore":
                continue
            yield path, Path(module) / path.relative_to(base)


def main():
    manifest = ast.literal_eval((ROOT / "my_modules" / MODULES[0] / "__manifest__.py").read_text(encoding="utf-8"))
    version = manifest["version"]
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    target = out_dir / f"vn_accounting_addons_{version}_{datetime.date.today():%Y%m%d}.zip"
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for module in MODULES:
            for path, arcname in module_files(module):
                archive.write(path, arcname.as_posix())
                count += 1
        archive.write(ROOT / "tools" / "vn_accounting" / "DEPLOY.md", "DEPLOY.md")
        archive.write(ROOT / "docs" / "vn_accounting" / "VN_Accounting_Documentation.pdf", "VN_Accounting_Documentation.pdf")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target}  ({count} module files, sha256 {digest})")


if __name__ == "__main__":
    main()
