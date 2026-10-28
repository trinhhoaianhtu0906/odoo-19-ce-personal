"""Daily stock ledger: quantities and values per product, per day with activity.

One row per (company, scope, product, day with activity), where the scope is the whole
company (0) or one warehouse. A row holds the movements of the day and the balance at the
end of the day, so that:

- the balance at any date is the last row on or before that date (one index probe per product);
- the movements between two dates are the sum of the rows in between.

The values replay the Odoo valuation (standard cost, average cost, FIFO) once, when the rows
are written, instead of at every report. The ledger is kept up to date incrementally: only the
products with a stock move or a cost change since the last sync are recomputed, from the day
of the change on.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

import pytz
from psycopg2.extras import execute_values

from odoo import api, fields, models
from odoo.tools import SQL
from odoo.tools.sql import create_index

COMPANY_SCOPE = 0
# Moves written by a transaction that started before the last sync but committed after it
# are caught by looking back a little; rebuilding a product twice is harmless.
SYNC_OVERLAP = timedelta(minutes=2)
CRON_OVERLAP = timedelta(days=1)
LOT_VALUATED = "lot"

LEDGER_COLUMNS = (
    "company_id",
    "product_id",
    "scope",
    "date",
    "in_qty",
    "out_qty",
    "transfer_in_qty",
    "transfer_out_qty",
    "in_value",
    "out_value",
    "closing_qty",
    "closing_value",
    "state_value",
    "unit_cost",
)


def ledger_tz(company):
    """Ledger days are calendar days in the company's timezone (Vietnam by default)."""
    return pytz.timezone(company.partner_id.tz or "Asia/Ho_Chi_Minh")


def local_day(moment, tz):
    if moment.year == 1:  # datetime.min: the initial cost of a product
        return date.min
    return pytz.utc.localize(moment).astimezone(tz).date()


def utc_moment(day, moment, tz):
    if day == date.min:
        return datetime.min
    return tz.localize(datetime.combine(day, moment)).astimezone(pytz.utc).replace(tzinfo=None)


class VnStockLedgerSync(models.Model):
    _name = "vn.stock.ledger.sync"
    _description = "Stock ledger sync state"
    _log_access = False

    company_id = fields.Many2one("res.company", required=True, ondelete="cascade")
    synced_at = fields.Datetime()

    _company_uniq = models.Constraint("UNIQUE (company_id)", "One sync state per company.")


class VnStockLedgerProduct(models.Model):
    _name = "vn.stock.ledger.product"
    _description = "Stock ledger product"
    _log_access = False

    company_id = fields.Many2one("res.company", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, ondelete="cascade")
    cost_method = fields.Char(help="Cost method the rows were computed with ('lot': not in the ledger).")

    _company_product_uniq = models.Constraint("UNIQUE (company_id, product_id)", "One entry per product.")


class VnStockLedger(models.Model):
    _name = "vn.stock.ledger"
    _description = "Daily stock ledger"
    _log_access = False
    _order = "date, id"

    company_id = fields.Many2one("res.company", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True, ondelete="cascade")
    scope = fields.Integer(required=True, help="0 for the whole company, else the warehouse id.")
    date = fields.Date(required=True)
    in_qty = fields.Float()
    out_qty = fields.Float()
    transfer_in_qty = fields.Float(help="From the other warehouses (warehouse scope only).")
    transfer_out_qty = fields.Float(help="To the other warehouses (warehouse scope only).")
    in_value = fields.Float()
    out_value = fields.Float()
    closing_qty = fields.Float()
    closing_value = fields.Float(help="Stock value at the end of the day (company scope only).")
    state_value = fields.Float(help="Average cost replay: running value, even when the quantity is zero.")
    unit_cost = fields.Float(help="Average cost, or standard cost, at the end of the day.")

    def init(self):
        cr = self.env.cr
        create_index(cr, "vn_stock_ledger_balance_idx", self._table, ["company_id", "scope", "product_id", "date"])
        create_index(cr, "vn_stock_ledger_period_idx", self._table, ["company_id", "scope", "date"])
        # Find what changed since the last sync without scanning the whole history
        create_index(cr, "vn_stock_ledger_stock_move_write_idx", "stock_move", ["company_id", "write_date"])
        create_index(cr, "vn_stock_ledger_product_value_write_idx", "product_value", ["company_id", "write_date"])

    # -- sync ----------------------------------------------------------------

    @api.model
    def _cron_sync(self):
        for company in self.env["res.company"].search([]):
            self._sync(company, overlap=CRON_OVERLAP)

    @api.model
    def _sync(self, company, overlap=SYNC_OVERLAP):
        """Bring the ledger of a company up to date. Cost: the changes since the last sync."""
        self = self.sudo()
        cr = self.env.cr
        for model in ("stock.move", "stock.move.line", "product.value"):
            self.env[model].flush_model()
        now = cr.now()
        cr.execute(SQL("SELECT synced_at FROM vn_stock_ledger_sync WHERE company_id = %s", company.id))
        row = cr.fetchone()
        if row and row[0]:
            changes = self._changed_products(company, row[0] - overlap)
        else:
            changes = self._all_products(company)
        for product_id in self._cost_method_changes(company):
            changes[product_id] = None
        if not changes and row:
            return
        # Two syncs of the same company: the second one waits here, then fails to serialize
        # and Odoo retries the request, which then sees the ledger written by the first one.
        cr.execute(
            SQL(
                """
                INSERT INTO vn_stock_ledger_sync (company_id, synced_at) VALUES (%s, %s)
                ON CONFLICT (company_id) DO UPDATE SET synced_at = EXCLUDED.synced_at
                """,
                company.id,
                now,
            )
        )
        if changes:
            self._rebuild(company, changes)

    def _all_products(self, company):
        self.env.cr.execute(
            SQL("SELECT DISTINCT product_id FROM stock_move WHERE company_id = %s AND state = 'done'", company.id)
        )
        return {product_id: None for (product_id,) in self.env.cr.fetchall()}

    def _changed_products(self, company, since):
        """Products with a move or a cost change written since `since`, with the date to rebuild from."""
        self.env.cr.execute(
            SQL(
                """
                SELECT product_id, MIN(date) FROM stock_move
                 WHERE company_id = %(company)s AND state = 'done' AND write_date >= %(since)s
                 GROUP BY product_id
                 UNION ALL
                SELECT COALESCE(pv.product_id, sm.product_id), MIN(COALESCE(sm.date, pv.date))
                  FROM product_value pv
                  LEFT JOIN stock_move sm ON sm.id = pv.move_id
                 WHERE pv.company_id = %(company)s AND pv.write_date >= %(since)s
                 GROUP BY 1
                """,
                company=company.id,
                since=since,
            )
        )
        changes = {}
        for product_id, moment in self.env.cr.fetchall():
            if product_id and (product_id not in changes or moment < changes[product_id]):
                changes[product_id] = moment
        return changes

    def _cost_method_changes(self, company):
        """Products whose cost method (category setting, lot valuation) changed since they were computed."""
        self.env.cr.execute(
            SQL(
                """
                SELECT h.product_id, h.cost_method, pt.categ_id, pt.lot_valuated
                  FROM vn_stock_ledger_product h
                  JOIN product_product pp ON pp.id = h.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                 WHERE h.company_id = %s
                """,
                company.id,
            )
        )
        rows = self.env.cr.fetchall()
        categories = self.env["product.category"].with_company(company).browse({row[2] for row in rows})
        method_by_categ = {categ.id: categ.property_cost_method for categ in categories}
        return [
            product_id
            for product_id, method, categ_id, lot_valuated in rows
            if method != (LOT_VALUATED if lot_valuated else method_by_categ.get(categ_id))
        ]

    # -- rebuild -------------------------------------------------------------

    def _rebuild(self, company, changes):
        """Recompute the rows of the given products from the given moment (None: from the start)."""
        cr = self.env.cr
        tz = ledger_tz(company)
        products = self.env["product.product"].with_company(company).with_context(active_test=False)
        products = products.browse(list(changes)).exists()
        cr.execute(
            SQL(
                "SELECT product_id FROM vn_stock_ledger_product WHERE company_id = %s AND product_id = ANY(%s)",
                company.id,
                products.ids,
            )
        )
        known = {product_id for (product_id,) in cr.fetchall()}
        start_day = {}
        for product in products:
            moment = changes[product.id]
            start_day[product.id] = local_day(moment, tz) if moment and product.id in known else date.min

        product_ids = products.ids
        days = [start_day[pid] for pid in product_ids]
        cr.execute(
            SQL(
                """
                DELETE FROM vn_stock_ledger l
                 USING unnest(%s::int[], %s::date[]) AS c(product_id, start_day)
                 WHERE l.company_id = %s AND l.product_id = c.product_id AND l.date >= c.start_day
                """,
                product_ids,
                days,
                company.id,
            )
        )
        methods = {
            product.id: LOT_VALUATED if product.lot_valuated else product.cost_method for product in products
        }
        execute_values(
            cr._obj,
            """
            INSERT INTO vn_stock_ledger_product (company_id, product_id, cost_method) VALUES %s
            ON CONFLICT (company_id, product_id) DO UPDATE SET cost_method = EXCLUDED.cost_method
            """,
            [(company.id, pid, methods[pid]) for pid in product_ids],
        )
        products = products.filtered(lambda p: p.is_storable and methods[p.id] != LOT_VALUATED)
        if not products:
            return

        locations = self._locations(company)
        warehouse_ids = (
            self.env["stock.warehouse"].with_context(active_test=False).search([("company_id", "=", company.id)]).ids
        )
        states = self._states_before(company, products, start_day, [COMPANY_SCOPE, *warehouse_ids])
        lines = self._fetch_lines(company, products, start_day, tz)
        manual = self._fetch_manual_values(company, products)

        rows = []
        fifo_rows = {}
        for product in products:
            product_rows, company_rows = self._replay(
                product,
                methods[product.id],
                start_day[product.id],
                lines.get(product.id, []),
                manual.get(product.id, []),
                states,
                locations,
                tz,
            )
            rows.extend(product_rows)
            if methods[product.id] == "fifo" and company_rows:
                fifo_rows[product] = company_rows
        if fifo_rows:
            self._value_fifo(company, fifo_rows, locations, tz)
        if rows:
            execute_values(
                cr._obj,
                f"INSERT INTO vn_stock_ledger ({', '.join(LEDGER_COLUMNS)}) VALUES %s",
                [tuple(row[column] for column in LEDGER_COLUMNS) for row in rows],
                page_size=1000,
            )
        self.invalidate_model()

    def _locations(self, company):
        """{location id: (valued, warehouse id of a valued location)}, as stock.location._should_be_valued."""
        self.env.cr.execute(
            SQL(
                """
                SELECT id, company_id = %s AND usage IN ('internal', 'transit'), warehouse_id
                  FROM stock_location
                """,
                company.id,
            )
        )
        return {loc_id: (bool(valued), warehouse_id if valued else None) for loc_id, valued, warehouse_id in self.env.cr.fetchall()}

    def _states_before(self, company, products, start_day, scopes):
        """Last row before the rebuild start, per (product, scope): one index probe each."""
        self.env.cr.execute(
            SQL(
                """
                SELECT c.product_id, s.scope, l.closing_qty, l.state_value, l.unit_cost
                  FROM unnest(%s::int[], %s::date[]) AS c(product_id, start_day)
                 CROSS JOIN unnest(%s::int[]) AS s(scope)
                 CROSS JOIN LATERAL (
                       SELECT closing_qty, state_value, unit_cost FROM vn_stock_ledger l
                        WHERE l.company_id = %s AND l.scope = s.scope AND l.product_id = c.product_id
                          AND l.date < c.start_day
                        ORDER BY l.date DESC LIMIT 1
                 ) l
                """,
                products.ids,
                [start_day[pid] for pid in products.ids],
                scopes,
                company.id,
            )
        )
        return {(pid, scope): (qty, value, unit_cost) for pid, scope, qty, value, unit_cost in self.env.cr.fetchall()}

    def _fetch_lines(self, company, products, start_day, tz):
        """The done move lines from the rebuild start on, per product, in move order."""
        self.env.cr.execute(
            SQL(
                """
                SELECT sm.product_id, sm.id, sm.date, sm.is_in, sm.is_out, sm.value, sm.quantity,
                       sml.location_id, sml.location_dest_id, sml.quantity_product_uom
                  FROM unnest(%s::int[], %s::timestamp[]) AS c(product_id, start_at)
                  JOIN stock_move sm ON sm.product_id = c.product_id AND sm.date >= c.start_at
                  JOIN stock_move_line sml ON sml.move_id = sm.id
                 WHERE sm.company_id = %s AND sm.state = 'done'
                   AND (sml.owner_id IS NULL OR sml.owner_id = %s)
                 ORDER BY sm.product_id, sm.date, sm.id
                """,
                products.ids,
                [utc_moment(start_day[pid], time.min, tz) for pid in products.ids],
                company.id,
                company.partner_id.id,
            )
        )
        lines = defaultdict(list)
        for product_id, *line in self.env.cr.fetchall():
            lines[product_id].append(line)
        return lines

    def _fetch_manual_values(self, company, products):
        """Cost changes (standard cost, average cost set by hand), per product, in date order."""
        self.env.cr.execute(
            SQL(
                """
                SELECT product_id, id, date, value FROM product_value
                 WHERE company_id = %s AND product_id = ANY(%s) AND move_id IS NULL AND lot_id IS NULL
                 ORDER BY product_id, date, id
                """,
                company.id,
                products.ids,
            )
        )
        manual = defaultdict(list)
        for product_id, pv_id, moment, value in self.env.cr.fetchall():
            manual[product_id].append((moment, pv_id, value))
        return manual

    def _replay(self, product, method, start, lines, manual, states, locations, tz):
        """Rows of one product from `start` on. Returns (all rows, company rows for the FIFO pass)."""
        uom = product.uom_id
        company_id = product.env.company.id
        qty, value, avg = states.get((product.id, COMPANY_SCOPE), (0.0, 0.0, None))
        qty, value = qty or 0.0, value or 0.0
        replay_qty = qty
        # Standard cost in force: the last cost change before the start, else the current cost
        price = product.standard_price
        for moment, _pv_id, pv_value in manual:
            if local_day(moment, tz) < start:
                price = pv_value
        if method == "standard" and avg is not None and start != date.min:
            price = avg
        warehouse_qty = defaultdict(float)
        for (pid, scope), state in states.items():
            if pid == product.id and scope != COMPANY_SCOPE:
                warehouse_qty[scope] = state[0] or 0.0

        # Moves before cost changes at the same moment, as the Odoo replay does
        events = []
        moves = defaultdict(list)
        for move_id, moment, is_in, is_out, move_value, move_qty, src, dst, line_qty in lines:
            if move_id not in moves:
                events.append((moment, 0, move_id, (is_in, is_out, move_value or 0.0, move_qty or 0.0)))
            moves[move_id].append((src, dst, line_qty or 0.0))
        for moment, pv_id, pv_value in manual:
            if local_day(moment, tz) >= start:
                events.append((moment, 1, pv_id, pv_value))
        events.sort(key=lambda event: event[:3])

        day_rows = {}
        warehouse_rows = {}

        def company_row(day):
            if day not in day_rows:
                day_rows[day] = dict.fromkeys(("in_qty", "out_qty", "in_value", "out_value"), 0.0)
            return day_rows[day]

        def warehouse_row(scope, day):
            key = (scope, day)
            if key not in warehouse_rows:
                warehouse_rows[key] = dict.fromkeys(
                    ("in_qty", "out_qty", "in_value", "out_value", "transfer_in_qty", "transfer_out_qty"), 0.0
                )
            return warehouse_rows[key]

        def close_day(day):
            row = day_rows[day]
            row.update(closing_qty=qty, state_value=value, unit_cost=price if method == "standard" else avg)
            if method == "standard":
                row["closing_value"] = qty * price
            elif method == "average":
                row["closing_value"] = 0.0 if uom.is_zero(qty) else value
            else:
                row["closing_value"] = 0.0  # set by the FIFO pass
            for scope, scope_day in list(warehouse_rows):
                if scope_day == day:
                    warehouse_rows[scope, day]["closing_qty"] = warehouse_qty[scope]

        # A cost change before the first move (the initial cost of the product) only sets the cost
        started = (product.id, COMPANY_SCOPE) in states
        current_day = None
        for moment, kind, _ref, data in events:
            day = local_day(moment, tz)
            if started or kind == 0:
                # Close the previous day before this event changes the quantity or the cost
                if current_day is not None and day != current_day:
                    close_day(current_day)
                current_day = day
                row = company_row(day)
            if kind == 1:  # cost change
                if method == "average":
                    # Odoo restarts the replay from the quantity on hand at the cost change
                    avg = data
                    replay_qty = qty
                    value = avg * qty
                elif method == "standard":
                    price = data
                continue
            started = True

            is_in, is_out, move_value, move_qty = data
            in_qty = out_qty = 0.0
            flows = []
            for src, dst, line_qty in moves[_ref]:
                src_valued, src_wh = locations.get(src, (False, None))
                dst_valued, dst_wh = locations.get(dst, (False, None))
                crosses = src_valued != dst_valued
                if crosses:
                    if dst_valued:
                        in_qty += line_qty
                    else:
                        out_qty += line_qty
                if src_wh != dst_wh:
                    flows.append((src_wh, dst_wh, line_qty, crosses))
            valued_qty = in_qty + out_qty
            unit = (move_value / valued_qty) if (is_in or is_out) and valued_qty else 0.0
            row["in_qty"] += in_qty
            row["out_qty"] += out_qty
            row["in_value"] += unit * in_qty
            row["out_value"] += unit * out_qty
            # Warehouse receipts and issues include the transfers with the other warehouses;
            # transfer_* tell them apart, as they have no value of their own.
            for src_wh, dst_wh, line_qty, crosses in flows:
                if src_wh:
                    wh_row = warehouse_row(src_wh, day)
                    wh_row["out_qty"] += line_qty
                    if crosses:
                        wh_row["out_value"] += unit * line_qty
                    else:
                        wh_row["transfer_out_qty"] += line_qty
                    warehouse_qty[src_wh] -= line_qty
                if dst_wh:
                    wh_row = warehouse_row(dst_wh, day)
                    wh_row["in_qty"] += line_qty
                    if crosses:
                        wh_row["in_value"] += unit * line_qty
                    else:
                        wh_row["transfer_in_qty"] += line_qty
                    warehouse_qty[dst_wh] += line_qty

            # Average cost, as stock_account _run_average_batch
            if method == "average":
                if is_in and in_qty:
                    previous_qty = replay_qty
                    replay_qty += in_qty
                    if previous_qty > 0:
                        value += move_value
                        avg = value / replay_qty
                    else:
                        avg = move_value / in_qty
                        value = avg * replay_qty
                if is_out and out_qty:
                    if avg is None:
                        avg = move_value / out_qty
                    value -= out_qty * avg
                    replay_qty -= out_qty
            qty += in_qty - out_qty
            if method != "average":
                replay_qty = qty
        if current_day is not None:
            close_day(current_day)

        rows = []
        for day, row in day_rows.items():
            rows.append(
                {
                    "company_id": company_id,
                    "product_id": product.id,
                    "scope": COMPANY_SCOPE,
                    "date": day,
                    "transfer_in_qty": 0.0,
                    "transfer_out_qty": 0.0,
                    **row,
                }
            )
        for (scope, day), row in warehouse_rows.items():
            rows.append(
                {
                    "company_id": company_id,
                    "product_id": product.id,
                    "scope": scope,
                    "date": day,
                    "closing_value": 0.0,
                    "state_value": 0.0,
                    "unit_cost": None,
                    **row,
                }
            )
        company_rows = [row for row in rows if row["scope"] == COMPANY_SCOPE]
        return rows, company_rows

    def _value_fifo(self, company, rows_by_product, locations, tz):
        """FIFO value at the end of each day, as stock_account _run_fifo: the latest receipts that
        cover the quantity on hand. Only the receipts that can be needed are read."""
        valued = [loc_id for loc_id, (is_valued, _wh) in locations.items() if is_valued]
        products = list(rows_by_product)
        bounds = []
        for product in products:
            rows = rows_by_product[product]
            received = sum(row["in_qty"] for row in rows)
            bounds.append(max(0.0, *(row["closing_qty"] for row in rows)) + received)
        self.env.cr.execute(
            SQL(
                """
                WITH layers AS (
                    SELECT sm.product_id, sm.id, sm.date, sm.value, sm.quantity,
                           SUM(sml.quantity_product_uom) AS qty
                      FROM stock_move sm
                      JOIN stock_move_line sml ON sml.move_id = sm.id
                     WHERE sm.company_id = %(company)s AND sm.state = 'done' AND sm.is_in
                       AND sm.product_id = ANY(%(products)s)
                       AND sml.picked
                       AND (sml.owner_id IS NULL OR sml.owner_id = %(owner)s)
                       AND sml.location_id <> ALL(%(valued)s) AND sml.location_dest_id = ANY(%(valued)s)
                     GROUP BY sm.id
                ), ranked AS (
                    SELECT *, SUM(qty) OVER (PARTITION BY product_id ORDER BY date DESC, id DESC) - qty AS before
                      FROM layers
                )
                SELECT r.product_id, r.date, r.value, r.quantity, r.qty
                  FROM ranked r
                  JOIN unnest(%(products)s::int[], %(bounds)s::float8[]) AS b(product_id, bound)
                    ON b.product_id = r.product_id
                 WHERE r.before <= b.bound
                 ORDER BY r.product_id, r.date DESC, r.id DESC
                """,
                company=company.id,
                products=[p.id for p in products],
                bounds=bounds,
                owner=company.partner_id.id,
                valued=valued,
            )
        )
        layers = defaultdict(list)
        for product_id, moment, value, move_qty, qty in self.env.cr.fetchall():
            layers[product_id].append((moment, value or 0.0, move_qty or 0.0, qty or 0.0))
        for product in products:
            uom = product.uom_id
            product_layers = layers[product.id]
            for row in rows_by_product[product]:
                day_end = utc_moment(row["date"], time(23, 59, 59), tz)
                quantity = row["closing_qty"]
                available = [layer for layer in product_layers if layer[0] <= day_end]
                if uom.compare(quantity, 0) <= 0:
                    if uom.is_zero(quantity):
                        row["closing_value"] = 0.0
                    else:
                        last = available[0] if available else None
                        unit = last[1] / last[3] if last and last[3] else product.standard_price
                        row["closing_value"] = quantity * unit
                    continue
                cost = 0.0
                remaining = quantity
                last = None
                for layer in available:
                    if remaining <= 0:
                        break
                    _moment, value, _move_qty, layer_qty = layer
                    take = min(layer_qty, remaining)
                    cost += value * take / layer_qty if layer_qty else 0.0
                    remaining -= take
                    if last is None:
                        last = layer
                if remaining > 0:
                    # More on hand than received: extrapolate with the last receipt, as Odoo does
                    if last and last[2]:
                        cost += remaining * last[1] / last[2]
                    else:
                        cost += remaining * product.standard_price
                row["closing_value"] = cost
