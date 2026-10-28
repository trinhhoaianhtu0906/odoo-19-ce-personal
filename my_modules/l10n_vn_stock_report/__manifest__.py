{  # noqa: B018
    "name": "Vietnam - Stock Movement Summary",
    "version": "19.0.1.0.0",
    "summary": "Stock movement summary: opening, receipts, issues and closing stock, in quantity and value",
    "description": """
Stock movement summary (Vietnamese "bao cao xuat nhap ton") for one company,
optionally one warehouse, over a period.

For every storable product: opening stock, receipts, issues and closing stock,
each in quantity and value.

- Quantities come from the done stock move lines, so closing = opening +
  receipts - issues always holds.
- Opening and closing values come from the Odoo valuation at that date
  (standard, average or FIFO cost), so they match the Stock Valuation report.
- Receipt and issue values are the values of the stock moves.
- Whatever else changed the stock value in the period (cost revaluation,
  landed costs, vendor bill price corrections) shows in a separate
  "Revaluation" column, so the value columns also add up.
- For one warehouse, transfers with other warehouses count as receipts and
  issues, valued at the weighted average cost of the period.

On-screen, PDF and XLSX output.
""",
    "category": "Inventory/Reporting",
    "author": "Tricasia",
    "license": "LGPL-3",
    "depends": ["stock_account"],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "report/stock_inout_templates.xml",
        "wizard/stock_inout_wizard_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "l10n_vn_stock_report/static/src/dynamic_report/*",
        ],
    },
    "installable": True,
}
