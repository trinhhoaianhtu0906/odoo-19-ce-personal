import base64
import io
from datetime import datetime, time, timedelta

import pytz
import xlsxwriter

from odoo import Command, api, fields, models
from odoo.fields import Domain
from odoo.tools import SQL, date_utils

from ..models.stock_ledger import COMPANY_SCOPE, ledger_tz

# Figures read per product by _read_movements()
MOVEMENT_KEYS = (
    "opening_qty",
    "in_qty",
    "out_qty",
    "in_value",
    "out_value",
    "transfer_in_qty",
    "transfer_out_qty",
)

# Amount columns of the report: (field, kind)
AMOUNT_COLUMNS = (
    ("opening_qty", "qty"),
    ("opening_value", "value"),
    ("in_qty", "qty"),
    ("in_value", "value"),
    ("out_qty", "qty"),
    ("out_value", "value"),
    ("revaluation_value", "value"),
    ("closing_qty", "qty"),
    ("closing_value", "value"),
)


def format_number(value, digits=0):
    """1234567.5 -> '1.234.567,5' with Vietnamese separators; negatives in brackets, zero as '-'."""
    if not value or round(value, digits) == 0:
        return "-"
    text = f"{abs(value):,.{digits}f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return f"({text})" if value < 0 else text


class VnStockInoutWizard(models.TransientModel):
    _name = "vn.stock.inout.wizard"
    _description = "Stock movement summary"

    def _default_date(self, granularity):
        today = fields.Date.context_today(self)
        if granularity == "start":
            return date_utils.start_of(today, "month")
        return date_utils.end_of(today, "month")

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        domain="[('company_id', '=', company_id)]",
        help="Leave empty for the whole company. For one warehouse, transfers with the other "
        "warehouses count as receipts and issues.",
    )
    date_from = fields.Date(string="Date From", required=True, default=lambda self: self._default_date("start"))
    date_to = fields.Date(string="Date To", required=True, default=lambda self: self._default_date("end"))
    categ_ids = fields.Many2many("product.category", string="Product Categories")
    product_ids = fields.Many2many("product.product", string="Products", domain="[('is_storable', '=', True)]")
    hide_zero = fields.Boolean(string="Hide Empty Lines", default=True)
    line_ids = fields.One2many("vn.stock.inout.line", "wizard_id", string="Lines")
    computed = fields.Boolean(readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    has_revaluation = fields.Boolean(compute="_compute_has_revaluation")
    xlsx_file = fields.Binary(readonly=True, attachment=False)
    xlsx_filename = fields.Char()

    _check_dates = models.Constraint(
        "CHECK (date_from <= date_to)",
        "The start date must be before the end date.",
    )

    @api.depends("line_ids.revaluation_value")
    def _compute_has_revaluation(self):
        for wizard in self:
            wizard.has_revaluation = any(
                not wizard.currency_id.is_zero(line.revaluation_value) for line in wizard.line_ids
            )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self.warehouse_id.company_id != self.company_id:
            self.warehouse_id = False

    @api.onchange("company_id", "warehouse_id", "date_from", "date_to", "categ_ids", "product_ids", "hide_zero")
    def _onchange_reset(self):
        self.line_ids = [Command.clear()]
        self.computed = False

    # -- computation -------------------------------------------------------

    def _utc_bounds(self):
        """First and last second of the period, in the company's timezone (the ledger days), as naive UTC."""
        tz = ledger_tz(self.company_id)

        def to_utc(day, moment):
            return tz.localize(datetime.combine(day, moment)).astimezone(pytz.utc).replace(tzinfo=None)

        return to_utc(self.date_from, time.min), to_utc(self.date_to, time(23, 59, 59))

    def _valued_locations(self):
        """The locations whose stock the company values (see stock.location._should_be_valued)."""
        return (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search([("company_id", "=", self.company_id.id), ("usage", "in", ("internal", "transit"))])
        )

    def _scope_locations(self):
        """The locations the report covers: the warehouse, or every valued location of the company."""
        if not self.warehouse_id:
            return self._valued_locations()
        return (
            self.env["stock.location"]
            .with_context(active_test=False)
            .search(
                [
                    ("id", "child_of", self.warehouse_id.view_location_id.id),
                    ("usage", "in", ("internal", "transit")),
                ]
            )
        )

    def _product_domain(self):
        domain = Domain("is_storable", "=", True) & Domain("company_id", "in", [False, self.company_id.id])
        if self.categ_ids:
            domain &= Domain("categ_id", "child_of", self.categ_ids.ids)
        if self.product_ids:
            domain &= Domain("id", "in", self.product_ids.ids)
        return domain

    def _read_movements(self, products, scope, valued, date_start, date_end):
        """Quantities and values that entered or left `scope`, per product id.

        Every done move line that crosses the border of `scope` counts. A line that also
        crosses the border of the valued locations takes its share of the move value;
        any other line is a transfer inside the company, which has no value of its own.
        Consigned stock (owned by another partner) is left out, as in the valuation.
        """
        self.env["stock.move"].flush_model(["state", "date", "company_id", "value", "is_in", "is_out"])
        self.env["stock.move.line"].flush_model(
            ["move_id", "product_id", "location_id", "location_dest_id", "owner_id", "quantity_product_uom"]
        )
        query = SQL(
            """
            WITH lines AS (
                SELECT sml.product_id,
                       sml.move_id,
                       sm.date,
                       sml.quantity_product_uom AS qty,
                       sml.location_dest_id = ANY(%(scope)s) AS incoming,
                       (sml.location_id = ANY(%(valued)s)) <> (sml.location_dest_id = ANY(%(valued)s)) AS valued,
                       CASE WHEN sm.is_in OR sm.is_out THEN sm.value ELSE 0 END AS move_value
                  FROM stock_move_line sml
                  JOIN stock_move sm ON sm.id = sml.move_id
                 WHERE sm.state = 'done'
                   AND sm.company_id = %(company)s
                   AND sm.date <= %(date_end)s
                   AND sml.product_id = ANY(%(products)s)
                   AND (sml.owner_id IS NULL OR sml.owner_id = %(owner)s)
                   AND (sml.location_id = ANY(%(scope)s)) <> (sml.location_dest_id = ANY(%(scope)s))
            ),
            move_qty AS (
                SELECT sml.move_id, SUM(sml.quantity_product_uom) AS qty
                  FROM stock_move_line sml
                 WHERE sml.move_id IN (SELECT move_id FROM lines WHERE valued AND date >= %(date_start)s)
                   AND (sml.owner_id IS NULL OR sml.owner_id = %(owner)s)
                   AND (sml.location_id = ANY(%(valued)s)) <> (sml.location_dest_id = ANY(%(valued)s))
                 GROUP BY sml.move_id
            )
            SELECT l.product_id,
                   SUM(CASE WHEN l.date < %(date_start)s THEN CASE WHEN l.incoming THEN l.qty ELSE -l.qty END END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND l.incoming THEN l.qty END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND NOT l.incoming THEN l.qty END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND l.incoming AND l.valued
                            THEN l.move_value * l.qty / NULLIF(mq.qty, 0) END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND NOT l.incoming AND l.valued
                            THEN l.move_value * l.qty / NULLIF(mq.qty, 0) END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND l.incoming AND NOT l.valued THEN l.qty END),
                   SUM(CASE WHEN l.date >= %(date_start)s AND NOT l.incoming AND NOT l.valued THEN l.qty END)
              FROM lines l
              LEFT JOIN move_qty mq ON mq.move_id = l.move_id
             GROUP BY l.product_id
            """,
            scope=scope.ids,
            valued=valued.ids,
            products=products.ids,
            company=self.company_id.id,
            owner=self.company_id.partner_id.id,
            date_start=date_start,
            date_end=date_end,
        )
        result = {}
        for product_id, *figures in self.env.execute_query(query):
            result[product_id] = dict(zip(MOVEMENT_KEYS, (float(figure or 0.0) for figure in figures)))
        return result

    def _stock_values(self, products, at):
        """Stock value per product id at a datetime, from the Odoo valuation."""
        company = self.company_id
        products = products.with_company(company).with_context(allowed_company_ids=company.ids, to_date=at)
        values = {product.id: product.total_value for product in products}
        # At a past date, Odoo values standard-cost products at the current cost until their first
        # cost change: it skips the initial cost, stored at datetime.min. Use the cost in force then.
        standard = products.filtered(lambda p: p.cost_method == "standard" and not p.lot_valuated)
        if standard:
            cost_at_date = standard._get_last_product_value(at)
            for product in standard._with_valuation_context():
                cost = cost_at_date[product].value if product in cost_at_date else product.standard_price
                values[product.id] = product.qty_available * cost
        return values

    def _get_rows(self):
        """One dict of line values per product, in display order, from the daily stock ledger."""
        self.ensure_one()
        products = self.env["product.product"].with_context(active_test=False).search(self._product_domain())
        self.env["vn.stock.ledger"]._sync(self.company_id)
        # Lot valuation is not in the ledger: those products go through the Odoo valuation
        lot_products = products.filtered("lot_valuated")
        figures = self._ledger_figures(products - lot_products)
        if lot_products:
            for part, extra in zip(figures, self._legacy_figures(lot_products)):
                part.update(extra)
        return self._assemble_rows(*figures)

    def _get_rows_legacy(self):
        """Same rows, computed from the whole move history and the Odoo valuation (the reference)."""
        self.ensure_one()
        products = self.env["product.product"].with_context(active_test=False).search(self._product_domain())
        return self._assemble_rows(*self._legacy_figures(products))

    def _legacy_figures(self, products):
        date_start, date_end = self._utc_bounds()
        valued = self._valued_locations()
        company_moves = self._read_movements(products, valued, valued, date_start, date_end)
        moves = company_moves
        if self.warehouse_id:
            moves = self._read_movements(products, self._scope_locations(), valued, date_start, date_end)
        products = products.browse(sorted(moves))
        opening_values = self._stock_values(products, date_start - timedelta(seconds=1))
        closing_values = self._stock_values(products, date_end)
        return moves, company_moves, opening_values, closing_values

    def _ledger_balances(self, scope, day, product_ids):
        """{product id: (quantity, value)} at the end of `day`: the last ledger row on or before it."""
        query = SQL(
            """
            SELECT p.id, l.closing_qty, l.closing_value
              FROM unnest(%(products)s::int[]) AS p(id)
             CROSS JOIN LATERAL (
                   SELECT closing_qty, closing_value FROM vn_stock_ledger l
                    WHERE l.company_id = %(company)s AND l.scope = %(scope)s AND l.product_id = p.id
                      AND l.date <= %(day)s
                    ORDER BY l.date DESC LIMIT 1
             ) l
            """,
            products=product_ids,
            company=self.company_id.id,
            scope=scope,
            day=day,
        )
        return {pid: (qty or 0.0, value or 0.0) for pid, qty, value in self.env.execute_query(query)}

    def _ledger_movements(self, scope, product_ids):
        """{product id: movement figures} between the two dates: the sum of the ledger rows."""
        query = SQL(
            """
            SELECT product_id, SUM(in_qty), SUM(out_qty), SUM(in_value), SUM(out_value),
                   SUM(transfer_in_qty), SUM(transfer_out_qty)
              FROM vn_stock_ledger
             WHERE company_id = %(company)s AND scope = %(scope)s AND product_id = ANY(%(products)s)
               AND date BETWEEN %(date_from)s AND %(date_to)s
             GROUP BY product_id
            """,
            company=self.company_id.id,
            scope=scope,
            products=product_ids,
            date_from=self.date_from,
            date_to=self.date_to,
        )
        keys = ("in_qty", "out_qty", "in_value", "out_value", "transfer_in_qty", "transfer_out_qty")
        return {
            pid: dict(zip(keys, (figure or 0.0 for figure in figures)))
            for pid, *figures in self.env.execute_query(query)
        }

    def _ledger_scope_figures(self, scope, product_ids):
        opening = self._ledger_balances(scope, self.date_from - timedelta(days=1), product_ids)
        closing = self._ledger_balances(scope, self.date_to, product_ids)
        movements = self._ledger_movements(scope, product_ids)
        empty = dict.fromkeys(MOVEMENT_KEYS, 0.0)
        figures = {}
        for pid in closing:  # products with stock history up to the end of the period
            figures[pid] = {**empty, **movements.get(pid, {}), "opening_qty": opening.get(pid, (0.0, 0.0))[0]}
        return figures, opening, closing

    def _ledger_figures(self, products):
        company_moves, opening, closing = self._ledger_scope_figures(COMPANY_SCOPE, products.ids)
        opening_values = {pid: value for pid, (_qty, value) in opening.items()}
        closing_values = {pid: value for pid, (_qty, value) in closing.items()}
        moves = company_moves
        if self.warehouse_id:
            moves = self._ledger_scope_figures(self.warehouse_id.id, products.ids)[0]
        return moves, company_moves, opening_values, closing_values

    def _assemble_rows(self, moves, company_moves, opening_values, closing_values):
        currency = self.company_id.currency_id
        products = self.env["product.product"].with_context(active_test=False).browse(sorted(moves))
        empty = dict.fromkeys(MOVEMENT_KEYS, 0.0)

        rows = []
        for product in products:
            move = moves[product.id]
            opening_qty = move["opening_qty"]
            closing_qty = opening_qty + move["in_qty"] - move["out_qty"]
            # Round the company values first, so that the warehouse shares don't depend on float noise
            opening_value = currency.round(opening_values.get(product.id, 0.0))
            closing_value = currency.round(closing_values.get(product.id, 0.0))
            in_value, out_value = move["in_value"], move["out_value"]
            if self.warehouse_id:
                company_move = company_moves.get(product.id, empty)
                company_opening_qty = company_move["opening_qty"]
                company_closing_qty = company_opening_qty + company_move["in_qty"] - company_move["out_qty"]
                # The warehouse holds its share of the company stock value, as in the Odoo valuation
                opening_value = opening_value * opening_qty / company_opening_qty if company_opening_qty else 0.0
                closing_value = closing_value * closing_qty / company_closing_qty if company_closing_qty else 0.0
                unit_cost = self._period_unit_cost(product, company_move, opening_values, closing_values)
                in_value += move["transfer_in_qty"] * unit_cost
                out_value += move["transfer_out_qty"] * unit_cost
            row = {
                "product_id": product.id,
                "opening_qty": opening_qty,
                "opening_value": currency.round(opening_value),
                "in_qty": move["in_qty"],
                "in_value": currency.round(in_value),
                "out_qty": move["out_qty"],
                "out_value": currency.round(out_value),
                "closing_qty": closing_qty,
                "closing_value": currency.round(closing_value),
            }
            row["revaluation_value"] = currency.round(
                row["closing_value"] - row["opening_value"] - row["in_value"] + row["out_value"]
            )
            if self.hide_zero and self._is_empty_row(row, product):
                continue
            rows.append(row)
        rows.sort(key=lambda row: self._sort_key(products.browse(row["product_id"])))
        for sequence, row in enumerate(rows, start=1):
            row["sequence"] = sequence
        return rows

    def _period_unit_cost(self, product, company_move, opening_values, closing_values):
        """Weighted average cost of the period for the company: (opening + receipts) / quantity."""
        quantity = company_move["opening_qty"] + company_move["in_qty"]
        if quantity > 0:
            return (opening_values.get(product.id, 0.0) + company_move["in_value"]) / quantity
        closing_qty = quantity - company_move["out_qty"]
        if closing_qty > 0:
            return closing_values.get(product.id, 0.0) / closing_qty
        return product.with_company(self.company_id).standard_price

    def _is_empty_row(self, row, product):
        currency = self.company_id.currency_id
        uom = product.uom_id
        return all(uom.is_zero(row[key]) for key, kind in AMOUNT_COLUMNS if kind == "qty") and all(
            currency.is_zero(row[key]) for key, kind in AMOUNT_COLUMNS if kind == "value"
        )

    def _sort_key(self, product):
        return (product.categ_id.complete_name or "", product.default_code or "", product.name or "")

    def _compute_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.write({"line_ids": [Command.create(row) for row in self._get_rows()], "computed": True})

    # -- dynamic report (client action) ---------------------------------

    _DYNAMIC_OPTIONS = ("company_id", "warehouse_id", "date_from", "date_to", "categ_ids", "hide_zero")

    @api.model
    def get_dynamic_options(self):
        """Choices for the filters of the on-screen report."""
        today = fields.Date.context_today(self)
        # Only the companies active in the company switcher: the drill-down and the exports
        # read their records with the user's active companies.
        companies = self.env.companies
        warehouses = self.env["stock.warehouse"].search([("company_id", "in", companies.ids)])
        categories = self.env["product.category"].search([], order="complete_name")
        return {
            "companies": [{"id": c.id, "name": c.name} for c in companies],
            "company_id": self.env.company.id,
            "warehouses": [{"id": w.id, "name": w.name, "company_id": w.company_id.id} for w in warehouses],
            "categories": [{"id": c.id, "name": c.complete_name} for c in categories],
            "date_from": fields.Date.to_string(date_utils.start_of(today, "month")),
            "date_to": fields.Date.to_string(date_utils.end_of(today, "month")),
        }

    @api.model
    def get_dynamic_report(self, options):
        """Compute the report for the on-screen view; the wizard id serves the exports and drill-downs."""
        vals = {key: value for key, value in options.items() if key in self._DYNAMIC_OPTIONS}
        vals["categ_ids"] = [Command.set(vals.get("categ_ids") or [])]
        wizard = self.with_company(vals["company_id"]).create(vals)
        wizard._compute_lines()
        return {
            "wizard_id": wizard.id,
            "company": wizard.company_id.name,
            "currency": wizard.currency_id.name,
            "period_text": wizard.period_text(),
            "scope_text": wizard.scope_text(),
            "qty_digits": wizard.qty_digits(),
            "value_digits": wizard.currency_id.decimal_places,
            "has_revaluation": wizard.has_revaluation,
            "lines": [
                {
                    "id": line.id,
                    "sequence": line.sequence,
                    "code": line.default_code or "",
                    "name": line.product_name,
                    "uom": line.uom_id.name,
                    "categ_id": line.categ_id.id,
                    "categ": line.categ_id.complete_name or "",
                    **{key: line[key] for key, _kind in AMOUNT_COLUMNS},
                }
                for line in wizard.line_ids
            ],
        }

    # -- actions -------------------------------------------------------------

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "name": self.env._("Stock Movement Summary"),
        }

    def action_compute(self):
        self._compute_lines()
        return self._reopen()

    def _ensure_computed(self):
        if not self.computed:
            self._compute_lines()

    def action_open_lines(self):
        """The lines in a list view, to group, filter and export them."""
        self._ensure_computed()
        return {
            "type": "ir.actions.act_window",
            "res_model": "vn.stock.inout.line",
            "view_mode": "list",
            "views": [(self.env.ref("l10n_vn_stock_report.vn_stock_inout_line_view_list").id, "list")],
            "search_view_id": [self.env.ref("l10n_vn_stock_report.vn_stock_inout_line_view_search").id],
            "domain": [("wizard_id", "=", self.id)],
            "name": f"{self.env._('Stock Movement Summary')} - {self.period_text()}",
            "target": "current",
        }

    def action_print_pdf(self):
        self._ensure_computed()
        return self.env.ref("l10n_vn_stock_report.action_report_vn_stock_inout").report_action(self, config=False)

    def action_export_xlsx(self):
        self._ensure_computed()
        self.write(
            {
                "xlsx_file": base64.b64encode(self._render_xlsx()),
                "xlsx_filename": self._export_filename("xlsx"),
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/?model={self._name}&id={self.id}&field=xlsx_file"
            f"&filename_field=xlsx_filename&download=true",
            "target": "self",
        }

    # -- presentation helpers (used by QWeb and XLSX) ---------------------

    def _export_filename(self, ext=None):
        name = f"stock_movement_{self.date_from}_{self.date_to}"
        if self.warehouse_id:
            name += f"_{self.warehouse_id.code}"
        return f"{name}.{ext}" if ext else name

    def period_text(self):
        return self.env._(
            "From %(date_from)s to %(date_to)s",
            date_from=f"{self.date_from:%d/%m/%Y}",
            date_to=f"{self.date_to:%d/%m/%Y}",
        )

    def scope_text(self):
        if self.warehouse_id:
            return self.env._("Warehouse: %s", self.warehouse_id.name)
        return self.env._("All warehouses")

    def qty_digits(self):
        return self.env["decimal.precision"].precision_get("Product Unit")

    def format_cell(self, value, kind):
        return format_number(value, self.qty_digits() if kind == "qty" else self.currency_id.decimal_places)

    def amount_columns(self):
        """The amount columns to show: the revaluation column only when it has figures."""
        return [(key, kind) for key, kind in AMOUNT_COLUMNS if key != "revaluation_value" or self.has_revaluation]

    def column_groups(self):
        """Second header row: [(label, number of columns)]."""
        groups = [
            (self.env._("Opening Stock"), 2),
            (self.env._("Receipts"), 2),
            (self.env._("Issues"), 2),
        ]
        if self.has_revaluation:
            groups.append((self.env._("Revaluation"), 1))
        groups.append((self.env._("Closing Stock"), 2))
        return groups

    def column_label(self, kind):
        return self.env._("Quantity") if kind == "qty" else self.env._("Value")

    def totals(self):
        """Value totals; quantities in different units of measure are not added up."""
        return {key: sum(self.line_ids.mapped(key)) for key, kind in AMOUNT_COLUMNS if kind == "value"}

    def _render_xlsx(self):
        buffer = io.BytesIO()
        book = xlsxwriter.Workbook(buffer, {"in_memory": True})
        sheet = book.add_worksheet(self.env._("Stock Movement")[:31])
        base = {"font_name": "Times New Roman", "font_size": 11}
        qty_format = "#,##0" + ("." + "0" * self.qty_digits() if self.qty_digits() else "") + ";(#,##0);-"
        fmt = {
            "text": book.add_format(base),
            "bold": book.add_format({**base, "bold": True}),
            "title": book.add_format({**base, "bold": True, "font_size": 14, "align": "center"}),
            "center": book.add_format({**base, "align": "center", "italic": True}),
            "right": book.add_format({**base, "align": "right", "italic": True}),
            "head": book.add_format(
                {**base, "bold": True, "align": "center", "valign": "vcenter", "border": 1, "text_wrap": True}
            ),
            "cell": book.add_format({**base, "border": 1}),
            "cell_c": book.add_format({**base, "border": 1, "align": "center"}),
            "cell_b": book.add_format({**base, "border": 1, "bold": True}),
            "qty": book.add_format({**base, "border": 1, "num_format": qty_format}),
            "value": book.add_format({**base, "border": 1, "num_format": "#,##0;(#,##0);-"}),
            "value_b": book.add_format({**base, "border": 1, "bold": True, "num_format": "#,##0;(#,##0);-"}),
        }
        columns = self.amount_columns()
        first = 4
        last = first + len(columns) - 1
        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 14)
        sheet.set_column(2, 2, 40)
        sheet.set_column(3, 3, 8)
        sheet.set_column(first, last, 15)

        company = self.company_id
        address = ", ".join(filter(None, [company.street, company.street2, company.city, company.state_id.name]))
        sheet.write(0, 0, self.env._("Company: %s", company.name), fmt["bold"])
        sheet.write(1, 0, self.env._("Address: %s", address), fmt["text"])
        sheet.merge_range(3, 0, 3, last, self.env._("STOCK MOVEMENT SUMMARY"), fmt["title"])
        sheet.merge_range(4, 0, 4, last, self.period_text(), fmt["center"])
        sheet.merge_range(5, 0, 5, last, self.scope_text(), fmt["center"])
        sheet.merge_range(6, 0, 6, last, self.env._("Currency: %s", company.currency_id.name), fmt["right"])

        row = 7
        for col, label in enumerate(
            [self.env._("No."), self.env._("Code"), self.env._("Product"), self.env._("UoM")]
        ):
            sheet.merge_range(row, col, row + 1, col, label, fmt["head"])
        col = first
        for label, width in self.column_groups():
            if width == 1:
                sheet.write(row, col, label, fmt["head"])
            else:
                sheet.merge_range(row, col, row, col + width - 1, label, fmt["head"])
            col += width
        for col, (_key, kind) in enumerate(columns, start=first):
            sheet.write(row + 1, col, self.column_label(kind), fmt["head"])
        row += 2

        for line in self.line_ids:
            sheet.write(row, 0, line.sequence, fmt["cell_c"])
            sheet.write(row, 1, line.default_code or "", fmt["cell"])
            sheet.write(row, 2, line.product_name, fmt["cell"])
            sheet.write(row, 3, line.uom_id.name or "", fmt["cell_c"])
            for col, (key, kind) in enumerate(columns, start=first):
                sheet.write_number(row, col, line[key], fmt[kind])
            row += 1

        totals = self.totals()
        sheet.merge_range(row, 0, row, 3, self.env._("Total"), fmt["cell_b"])
        for col, (key, kind) in enumerate(columns, start=first):
            if kind == "value":
                sheet.write_number(row, col, totals[key], fmt["value_b"])
            else:
                sheet.write_blank(row, col, None, fmt["cell"])
        sheet.freeze_panes(9, 3)
        book.close()
        return buffer.getvalue()


class VnStockInoutLine(models.TransientModel):
    _name = "vn.stock.inout.line"
    _description = "Stock movement summary line"
    _order = "sequence, id"

    wizard_id = fields.Many2one("vn.stock.inout.wizard", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(string="No.")
    product_id = fields.Many2one("product.product", string="Product", required=True)
    default_code = fields.Char(related="product_id.default_code", string="Code")
    product_name = fields.Char(related="product_id.name", string="Product Name")
    uom_id = fields.Many2one(related="product_id.uom_id", string="UoM")
    categ_id = fields.Many2one(related="product_id.categ_id", string="Product Category", store=True)
    currency_id = fields.Many2one(related="wizard_id.company_id.currency_id")
    opening_qty = fields.Float(string="Opening Qty", digits="Product Unit")
    opening_value = fields.Monetary(string="Opening Value")
    in_qty = fields.Float(string="Received Qty", digits="Product Unit")
    in_value = fields.Monetary(string="Received Value")
    out_qty = fields.Float(string="Issued Qty", digits="Product Unit")
    out_value = fields.Monetary(string="Issued Value")
    revaluation_value = fields.Monetary(
        string="Revaluation",
        help="Change in stock value not explained by the receipts and issues: cost revaluation, "
        "landed costs, vendor bill price corrections.",
    )
    closing_qty = fields.Float(string="Closing Qty", digits="Product Unit")
    closing_value = fields.Monetary(string="Closing Value")

    def action_open_move_lines(self):
        """The move lines behind the receipts and issues of the period (stock card)."""
        self.ensure_one()
        wizard = self.wizard_id
        date_start, date_end = wizard._utc_bounds()
        scope = wizard._scope_locations().ids
        crossing = (
            Domain("location_id", "in", scope) & Domain("location_dest_id", "not in", scope)
        ) | (Domain("location_id", "not in", scope) & Domain("location_dest_id", "in", scope))
        domain = (
            Domain("product_id", "=", self.product_id.id)
            & Domain("state", "=", "done")
            & Domain("move_id.company_id", "=", wizard.company_id.id)
            & Domain("move_id.date", ">=", fields.Datetime.to_string(date_start))
            & Domain("move_id.date", "<=", fields.Datetime.to_string(date_end))
            & crossing
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.move.line",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": list(domain),
            "context": {"create": False},
            "name": self.env._("Stock Moves: %s", self.product_id.display_name),
        }
