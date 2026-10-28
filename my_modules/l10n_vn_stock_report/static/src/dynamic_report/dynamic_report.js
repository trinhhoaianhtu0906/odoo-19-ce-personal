import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PERIODS = [
    ...Array.from({ length: 12 }, (_, i) => ({ key: `m${i + 1}`, label: _t("Month %s", i + 1), months: [i + 1, i + 1] })),
    { key: "q1", label: _t("Quarter 1"), months: [1, 3] },
    { key: "q2", label: _t("Quarter 2"), months: [4, 6] },
    { key: "q3", label: _t("Quarter 3"), months: [7, 9] },
    { key: "q4", label: _t("Quarter 4"), months: [10, 12] },
    { key: "h1", label: _t("First 6 Months"), months: [1, 6] },
    { key: "year", label: _t("Full Year"), months: [1, 12] },
    { key: "custom", label: _t("Custom Dates") },
];

// Amount columns: [field, kind, group]
const COLUMNS = [
    ["opening_qty", "qty", "opening"],
    ["opening_value", "value", "opening"],
    ["in_qty", "qty", "in"],
    ["in_value", "value", "in"],
    ["out_qty", "qty", "out"],
    ["out_value", "value", "out"],
    ["revaluation_value", "value", "revaluation"],
    ["closing_qty", "qty", "closing"],
    ["closing_value", "value", "closing"],
];

function pad(n) {
    return String(n).padStart(2, "0");
}

function lastDay(year, month) {
    return new Date(year, month, 0).getDate();
}

function normalize(text) {
    return (text || "")
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .replace(/đ/g, "d")
        .replace(/Đ/g, "D")
        .toLowerCase();
}

/**
 * On-screen stock movement summary: the figures load when the menu opens and are
 * recomputed whenever a filter changes; the search box and the grouping work on screen.
 */
export class VnStockInoutReport extends Component {
    static template = "l10n_vn_stock_report.DynamicReport";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.periods = PERIODS;
        this.state = useState({
            choices: null,
            options: {},
            year: new Date().getFullYear(),
            period: `m${new Date().getMonth() + 1}`,
            search: "",
            groupByCategory: false,
            data: null,
            loading: false,
            error: null,
            exporting: false,
        });
        this.requestId = 0;
        onWillStart(async () => {
            const choices = await this.orm.call("vn.stock.inout.wizard", "get_dynamic_options", []);
            this.state.choices = choices;
            this.state.year = Number(choices.date_to.slice(0, 4));
            this.state.period = `m${Number(choices.date_to.slice(5, 7))}`;
            this.state.options = {
                company_id: choices.company_id,
                warehouse_id: false,
                categ_ids: [],
                date_from: choices.date_from,
                date_to: choices.date_to,
                hide_zero: true,
            };
            await this.load();
        });
    }

    // -- getters ----------------------------------------------------------

    get years() {
        const current = new Date().getFullYear();
        return Array.from({ length: 8 }, (_, i) => current + 1 - i);
    }

    get warehouses() {
        return this.state.choices.warehouses.filter((w) => w.company_id === this.state.options.company_id);
    }

    get columns() {
        const data = this.state.data;
        return COLUMNS.filter(([key]) => key !== "revaluation_value" || data?.has_revaluation).map(
            ([key, kind, group]) => ({ key, kind, group })
        );
    }

    get columnGroups() {
        const labels = {
            opening: _t("Opening Stock"),
            in: _t("Receipts"),
            out: _t("Issues"),
            revaluation: _t("Revaluation"),
            closing: _t("Closing Stock"),
        };
        const groups = [];
        for (const column of this.columns) {
            const last = groups.at(-1);
            if (last?.key === column.group) {
                last.span++;
            } else {
                groups.push({ key: column.group, label: labels[column.group], span: 1 });
            }
        }
        return groups;
    }

    get visibleLines() {
        const lines = this.state.data?.lines || [];
        const terms = normalize(this.state.search).split(/\s+/).filter(Boolean);
        if (!terms.length) {
            return lines;
        }
        return lines.filter((line) => {
            const text = normalize(`${line.code} ${line.name} ${line.categ}`);
            return terms.every((term) => text.includes(term));
        });
    }

    /** Rows to display: product lines, with a header and a subtotal per category when grouped. */
    get rows() {
        const lines = this.visibleLines;
        if (!this.state.groupByCategory) {
            return lines.map((line) => ({ type: "line", key: `l${line.id}`, line }));
        }
        const groups = new Map();
        for (const line of lines) {
            if (!groups.has(line.categ)) {
                groups.set(line.categ, []);
            }
            groups.get(line.categ).push(line);
        }
        const rows = [];
        for (const [categ, groupLines] of groups) {
            rows.push({ type: "group", key: `g${categ}`, label: categ || _t("No Category"), totals: this.totals(groupLines) });
            rows.push(...groupLines.map((line) => ({ type: "line", key: `l${line.id}`, line })));
        }
        return rows;
    }

    get grandTotals() {
        return this.totals(this.visibleLines);
    }

    totals(lines) {
        const totals = {};
        for (const { key, kind } of this.columns) {
            if (kind === "value") {
                totals[key] = lines.reduce((sum, line) => sum + (line[key] || 0), 0);
            }
        }
        return totals;
    }

    // -- loading ----------------------------------------------------------

    async load() {
        const requestId = ++this.requestId;
        this.state.loading = true;
        try {
            const data = await this.orm.call("vn.stock.inout.wizard", "get_dynamic_report", [this.state.options]);
            if (requestId === this.requestId) {
                this.state.data = data;
                this.state.error = null;
            }
        } catch (error) {
            if (requestId === this.requestId) {
                this.state.data = null;
                this.state.error = error.data?.message || error.message || String(error);
            }
        } finally {
            if (requestId === this.requestId) {
                this.state.loading = false;
            }
        }
    }

    // -- filters ----------------------------------------------------------

    applyPeriod() {
        const period = PERIODS.find((p) => p.key === this.state.period);
        if (!period?.months) {
            return;
        }
        const year = this.state.year;
        const [first, last] = period.months;
        this.state.options.date_from = `${year}-${pad(first)}-01`;
        this.state.options.date_to = `${year}-${pad(last)}-${pad(lastDay(year, last))}`;
    }

    async onCompanyChange(ev) {
        this.state.options.company_id = Number(ev.target.value);
        this.state.options.warehouse_id = false;
        await this.load();
    }

    async onWarehouseChange(ev) {
        this.state.options.warehouse_id = Number(ev.target.value) || false;
        await this.load();
    }

    async onCategoryChange(ev) {
        const categId = Number(ev.target.value);
        this.state.options.categ_ids = categId ? [categId] : [];
        await this.load();
    }

    async onHideZeroChange(ev) {
        this.state.options.hide_zero = ev.target.checked;
        await this.load();
    }

    async onYearChange(ev) {
        this.state.year = Number(ev.target.value);
        if (this.state.period === "custom") {
            this.state.period = "year";
        }
        this.applyPeriod();
        await this.load();
    }

    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this.applyPeriod();
        if (this.state.period !== "custom") {
            await this.load();
        }
    }

    async onDateChange(key, ev) {
        if (!ev.target.value) {
            return;
        }
        this.state.options[key] = ev.target.value;
        if (this.state.options.date_from <= this.state.options.date_to) {
            await this.load();
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    onGroupChange(ev) {
        this.state.groupByCategory = ev.target.checked;
    }

    // -- actions ----------------------------------------------------------

    async export(method) {
        if (!this.state.data || this.state.exporting) {
            return;
        }
        this.state.exporting = true;
        try {
            const action = await this.orm.call("vn.stock.inout.wizard", method, [[this.state.data.wizard_id]]);
            await this.actionService.doAction(action);
        } finally {
            this.state.exporting = false;
        }
    }

    async openLine(line) {
        const action = await this.orm.call("vn.stock.inout.line", "action_open_move_lines", [[line.id]]);
        await this.actionService.doAction(action);
    }

    format(value, kind) {
        const digits = kind === "qty" ? this.state.data.qty_digits : this.state.data.value_digits;
        const factor = 10 ** digits;
        const rounded = Math.round((value || 0) * factor) / factor;
        if (!rounded) {
            return "-";
        }
        const text = Math.abs(rounded).toLocaleString("vi-VN", {
            minimumFractionDigits: kind === "qty" ? 0 : digits,
            maximumFractionDigits: digits,
        });
        return rounded < 0 ? `(${text})` : text;
    }
}

registry.category("actions").add("l10n_vn_stock_report.dynamic_report", VnStockInoutReport);
