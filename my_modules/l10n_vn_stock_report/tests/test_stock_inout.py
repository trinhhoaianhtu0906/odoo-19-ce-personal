from datetime import date

from freezegun import freeze_time

from odoo import fields
from odoo.tests import tagged

from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestStockInout(TestStockValuationCommon):
    def _report(self, products, date_from=date(2026, 2, 1), date_to=date(2026, 2, 28), **vals):
        wizard = (
            self.env["vn.stock.inout.wizard"]
            .with_context(tz="Asia/Ho_Chi_Minh")
            .create(
                {
                    "company_id": self.company.id,
                    "date_from": date_from,
                    "date_to": date_to,
                    "product_ids": [(6, 0, products.ids)],
                    **vals,
                }
            )
        )
        wizard._compute_lines()
        return wizard

    def _transfer(self, product, quantity, location, location_dest):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "location_dest_id": location_dest.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": quantity,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.picked = True
        move._action_done()
        return move

    def test_fifo(self):
        product = self.product_fifo
        with freeze_time("2026-01-10 03:00:00"):
            self._make_in_move(product, 10, 100)
        with freeze_time("2026-02-05 03:00:00"):
            self._make_in_move(product, 10, 120)
        with freeze_time("2026-02-20 03:00:00"):
            out_move = self._make_out_move(product, 15)
        with freeze_time("2026-03-05 03:00:00"):
            self._make_out_move(product, 2)
        self.assertEqual(out_move.value, 1600)  # 10 @ 100 + 5 @ 120

        wizard = self._report(product)
        self.assertRecordValues(
            wizard.line_ids,
            [
                {
                    "product_id": product.id,
                    "opening_qty": 10,
                    "opening_value": 1000,
                    "in_qty": 10,
                    "in_value": 1200,
                    "out_qty": 15,
                    "out_value": 1600,
                    "revaluation_value": 0,
                    "closing_qty": 5,
                    "closing_value": 600,
                }
            ],
        )
        self.assertFalse(wizard.has_revaluation)

    def test_average_cost_revaluation(self):
        product = self.product_avco
        with freeze_time("2026-01-10 03:00:00"):
            self._make_in_move(product, 10, 100)
        with freeze_time("2026-02-10 03:00:00"):
            product.standard_price = 150

        wizard = self._report(product)
        self.assertRecordValues(
            wizard.line_ids,
            [
                {
                    "opening_qty": 10,
                    "opening_value": 1000,
                    "in_qty": 0,
                    "out_qty": 0,
                    "revaluation_value": 500,
                    "closing_qty": 10,
                    "closing_value": 1500,
                }
            ],
        )
        self.assertTrue(wizard.has_revaluation)

    def test_standard_cost_change(self):
        """The cost change shows in the period it happened, not in the first period."""
        product = self.product_standard  # standard cost 10 since its creation
        with freeze_time("2026-01-10 03:00:00"):
            self._make_in_move(product, 10)
        with freeze_time("2026-02-10 03:00:00"):
            product.standard_price = 12

        # The initial cost alone (before any move) gives no line
        december = self._report(product, date(2025, 12, 1), date(2025, 12, 31), hide_zero=False)
        self.assertFalse(december.line_ids)
        january = self._report(product, date(2026, 1, 1), date(2026, 1, 31))
        self.assertRecordValues(
            january.line_ids, [{"in_qty": 10, "in_value": 100, "revaluation_value": 0, "closing_value": 100}]
        )
        february = self._report(product)
        self.assertRecordValues(
            february.line_ids, [{"opening_value": 100, "revaluation_value": 20, "closing_value": 120}]
        )

    def test_period_in_user_timezone(self):
        """A move on 31 January at 18:00 UTC is on 1 February in Vietnam (UTC+7)."""
        product = self.product_fifo
        with freeze_time("2026-01-31 18:00:00"):
            self._make_in_move(product, 10, 100)

        january = self._report(product, date(2026, 1, 1), date(2026, 1, 31))
        self.assertFalse(january.line_ids)
        february = self._report(product)
        self.assertRecordValues(
            february.line_ids,
            [{"opening_qty": 0, "opening_value": 0, "in_qty": 10, "in_value": 1000, "closing_value": 1000}],
        )

    def test_warehouse_transfer(self):
        self._use_multi_warehouses()
        product = self.product_standard
        other_stock = self.other_warehouse.lot_stock_id
        with freeze_time("2026-01-10 03:00:00"):
            self._make_in_move(product, 10, 10)
        with freeze_time("2026-02-10 03:00:00"):
            self._transfer(product, 4, self.stock_location, other_stock)

        company = self._report(product)
        self.assertRecordValues(
            company.line_ids,
            [{"opening_qty": 10, "opening_value": 100, "in_qty": 0, "out_qty": 0, "closing_value": 100}],
        )
        main = self._report(product, warehouse_id=self.warehouse.id)
        self.assertRecordValues(
            main.line_ids,
            [
                {
                    "opening_qty": 10,
                    "opening_value": 100,
                    "out_qty": 4,
                    "out_value": 40,
                    "revaluation_value": 0,
                    "closing_qty": 6,
                    "closing_value": 60,
                }
            ],
        )
        other = self._report(product, warehouse_id=self.other_warehouse.id)
        self.assertRecordValues(
            other.line_ids,
            [{"opening_qty": 0, "in_qty": 4, "in_value": 40, "revaluation_value": 0, "closing_value": 40}],
        )

    def test_consigned_stock_left_out(self):
        product = self.product_fifo
        with freeze_time("2026-02-05 03:00:00"):
            self._make_in_move(product, 10, 100)
            self._make_in_move(product, 5, 100, owner_id=self.owner.id)

        wizard = self._report(product)
        self.assertRecordValues(wizard.line_ids, [{"in_qty": 10, "in_value": 1000, "closing_qty": 10}])

    def _assert_ledger_matches_legacy(self, products, ranges, warehouses):
        """The daily ledger gives the same figures as the full-history computation."""
        for date_from, date_to in ranges:
            for warehouse in warehouses:
                wizard = self.env["vn.stock.inout.wizard"].create(
                    {
                        "company_id": self.company.id,
                        "warehouse_id": warehouse.id,
                        "date_from": date_from,
                        "date_to": date_to,
                        "product_ids": [(6, 0, products.ids)],
                        "hide_zero": False,
                    }
                )
                ledger, legacy = wizard._get_rows(), wizard._get_rows_legacy()
                label = f"{date_from} - {date_to} {warehouse.name or 'company'}"
                self.assertEqual([r["product_id"] for r in ledger], [r["product_id"] for r in legacy], label)
                for got, expected in zip(ledger, legacy):
                    for key, value in expected.items():
                        self.assertAlmostEqual(got[key], value, delta=0.01, msg=f"{label} {key}")

    def test_ledger_matches_legacy(self):
        self._use_multi_warehouses()
        fifo, avco, standard = self.product_fifo, self.product_avco, self.product_standard
        products = fifo | avco | standard
        other_stock = self.other_warehouse.lot_stock_id
        ranges = [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 2, 1), date(2026, 2, 28)),
            (date(2026, 1, 15), date(2026, 2, 14)),
            (date(2026, 2, 10), date(2026, 2, 10)),
            (date(2026, 1, 1), date(2026, 3, 31)),
        ]
        warehouses = [self.env["stock.warehouse"], self.warehouse, self.other_warehouse]

        with freeze_time("2026-01-05 03:00:00"):
            first_in = self._make_in_move(fifo, 10, 100)
            self._make_in_move(avco, 10, 100)
            self._make_in_move(standard, 10)
        with freeze_time("2026-01-20 18:30:00"):  # 21 January in Vietnam
            self._make_in_move(fifo, 5, 130)
            self._make_in_move(avco, 10, 160)
            self._make_out_move(standard, 3)
        # Sync the ledger, then keep changing things: the sync must pick up only the changes
        self._assert_ledger_matches_legacy(products, ranges, warehouses)

        with freeze_time("2026-02-03 03:00:00"):
            self._make_out_move(fifo, 12)
            self._make_out_move(avco, 4)
            self._transfer(avco, 6, self.stock_location, other_stock)
            self._make_in_move(fifo, 5, 100, owner_id=self.owner.id)  # consigned: left out
        with freeze_time("2026-02-10 03:00:00"):
            avco.standard_price = 150  # average cost set by hand
            standard.standard_price = 12
            self._transfer(fifo, 2, self.stock_location, other_stock)
            self._make_out_move(avco, 3, location_id=other_stock.id)
        self._assert_ledger_matches_legacy(products, ranges, warehouses)

        # A late vendor bill changes the value of a January receipt
        with freeze_time("2026-02-20 03:00:00"):
            first_in.value_manual = 1100
        self._assert_ledger_matches_legacy(products, ranges, warehouses)

        # Rebuilding from any day in the middle, from the stored state, gives the same rows
        # as rebuilding from the start
        Ledger = self.env["vn.stock.ledger"].sudo()
        columns = ("scope", "date", "in_qty", "out_qty", "in_value", "out_value", "transfer_in_qty",
                   "transfer_out_qty", "closing_qty", "closing_value", "state_value", "unit_cost")

        def ledger_rows():
            rows = Ledger.search_read([("product_id", "in", products.ids)], ["product_id", *columns])
            return sorted((r["product_id"][0], *(r[c] for c in columns)) for r in rows)

        Ledger._rebuild(self.company, dict.fromkeys(products.ids))
        full = ledger_rows()
        for moment in ("2026-01-20 20:00:00", "2026-02-03 00:00:00", "2026-02-10 03:00:00", "2026-02-21 00:00:00"):
            Ledger._rebuild(self.company, dict.fromkeys(products.ids, fields.Datetime.to_datetime(moment)))
            resumed = ledger_rows()
            self.assertEqual(len(resumed), len(full), moment)
            for got, expected in zip(resumed, full):
                self.assertEqual(got[:3], expected[:3], moment)
                for a, b in zip(got[3:], expected[3:]):
                    self.assertAlmostEqual(a or 0.0, b or 0.0, delta=1e-6, msg=f"{moment} {expected[:3]}")

    def test_dynamic_report(self):
        product = self.product_fifo
        with freeze_time("2026-02-05 03:00:00"):
            self._make_in_move(product, 10, 100)
        Wizard = self.env["vn.stock.inout.wizard"]
        choices = Wizard.get_dynamic_options()
        self.assertIn(self.warehouse.id, [w["id"] for w in choices["warehouses"]])
        data = Wizard.get_dynamic_report(
            {
                "company_id": self.company.id,
                "warehouse_id": False,
                "categ_ids": [product.categ_id.id],
                "date_from": "2026-02-01",
                "date_to": "2026-02-28",
                "hide_zero": True,
            }
        )
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["code"], product.default_code or "")
        self.assertEqual(data["lines"][0]["in_value"], 1000)
        self.assertTrue(Wizard.browse(data["wizard_id"])._render_xlsx())

    def test_exports(self):
        product = self.product_fifo
        with freeze_time("2026-02-05 03:00:00"):
            self._make_in_move(product, 10, 100)
        wizard = self._report(product)
        self.assertTrue(wizard._render_xlsx().startswith(b"PK"))
        html, _ = self.env["ir.actions.report"]._render_qweb_html(
            "l10n_vn_stock_report.report_vn_stock_inout", wizard.ids
        )
        self.assertIn(product.name, html.decode())
        action = wizard.line_ids.action_open_move_lines()
        self.assertEqual(len(self.env["stock.move.line"].search(action["domain"])), 1)
