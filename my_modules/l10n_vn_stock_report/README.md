# Vietnam - Stock Movement Summary

Stock movement summary (Vietnamese *báo cáo xuất nhập tồn*) for Odoo 19:
opening stock, receipts, issues and closing stock per product, in quantity
and value, for one company or one warehouse over a period.

Menus: **Inventory > Reporting > Stock Movement Summary** and
**Accounting > Reporting > Stock Movement Summary**.

## How the figures are computed

| Column | Source |
| --- | --- |
| Quantities | Done stock move lines that cross the border of the company's valued locations (or of the warehouse). Closing = opening + receipts - issues. |
| Opening / closing value | `product.product.total_value` at the first / last second of the period, i.e. the Odoo valuation (standard, average or FIFO). Matches the Stock Valuation report. |
| Receipt / issue value | `stock.move.value`, shared over the move lines by quantity. |
| Revaluation | Closing value - opening value - receipts + issues: cost revaluations, landed costs, vendor bill price corrections. Hidden when zero. |

- The period runs from 00:00 on the first day to 23:59:59 on the last day,
  in the user's timezone.
- Consigned stock (owner other than the company) is left out, as in the valuation.
- **One warehouse:** transfers with the other warehouses of the company count
  as receipts and issues. They have no value of their own, so they are valued
  at the company's weighted average cost of the period:
  (opening value + receipt value) / (opening qty + received qty).
  The warehouse's opening and closing values are its share of the company
  value by quantity, as in the Odoo valuation.
- Quantities are in the product's unit of measure and are not totalled.

## Daily stock ledger

The report does not read the whole move history. It reads `vn.stock.ledger`:
one row per (company or warehouse, product, day with activity), with the
movements of the day and the quantity and value at the end of the day.

- Balance at a date: the last row on or before it, one index probe per product.
- Movements between two dates: the sum of the rows in between.
- Per report: O(P log N + R), for P products and R ledger rows in the period,
  whatever the length of the history.

The values replay the Odoo valuation when the rows are written: average cost
as `_run_average_batch`, FIFO as `_run_fifo` (latest receipts covering the
quantity on hand), standard cost as quantity x cost in force.

The ledger is updated incrementally, before each report and by a nightly cron.
Only the products with a stock move or a cost change written since the last
sync are recomputed, from the day of the change, starting from the stored
state of the day before. A late vendor bill on an old receipt recomputes that
product from the receipt date. A change of costing method recomputes the
product from the start.

- Lot-valuated products are not in the ledger; they go through the Odoo valuation.
- Ledger days are calendar days in the company's timezone (Vietnam by default).
- After changing the replay code, empty the ledger so that it is rebuilt:
  `TRUNCATE vn_stock_ledger, vn_stock_ledger_product, vn_stock_ledger_sync`.
- The previous full-history computation is kept as `_get_rows_legacy()`; the
  tests check that both give the same figures.

## Output

- On screen (client action `l10n_vn_stock_report.dynamic_report`, like the VAS
  statements): the figures load when the menu opens and are recomputed whenever
  a filter changes (warehouse, year, month/quarter/year or custom dates, product
  category, hide empty lines). The search box and "Group by Category" (with
  subtotals) work on screen. Click a line for its stock moves.
- The company filter lists the companies active in the company switcher.
- PDF (A4 landscape) and XLSX, from the figures on screen.
