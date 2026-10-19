// Drive Chrome headless through the DevTools protocol: open the financial statements screen,
// collect JS errors, take screenshots, and switch filters to check live recompute.
// Usage: node ui_check.mjs <session_id> <out_dir>
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const [sessionId, outDir] = process.argv.slice(2);
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9333;
const BASE = "http://127.0.0.1:8069";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${join(outDir, "chrome-profile")}`,
    "--no-first-run", "--window-size=1600,1300", "about:blank",
]);
let target;
for (let i = 0; i < 40 && !target; i++) {
    await sleep(250);
    try {
        const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
        target = list.find((t) => t.type === "page");
    } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let nextId = 1;
const pending = new Map();
const errors = [];
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
    } else if (msg.method === "Runtime.exceptionThrown") {
        errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
        errors.push(msg.params.args.map((a) => a.value ?? a.description).join(" "));
    }
};
const send = (method, params = {}) =>
    new Promise((resolve) => {
        const id = nextId++;
        pending.set(id, resolve);
        ws.send(JSON.stringify({ id, method, params }));
    });
const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;
const shot = async (name) => {
    const res = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(outDir, name), Buffer.from(res.result.data, "base64"));
};
const waitIdle = async () => {
    for (let i = 0; i < 60; i++) {
        await sleep(500);
        const busy = await evaluate("!!document.querySelector('.o_vn_loading') || !document.querySelector('.o_vn_table')");
        if (!busy) return;
    }
};

await send("Runtime.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1300, deviceScaleFactor: 1, mobile: false });
await send("Network.enable");
await send("Network.setCookie", { name: "session_id", value: sessionId, domain: "127.0.0.1", path: "/" });
await send("Page.navigate", { url: `${BASE}/odoo/action-l10n_vn_financial_statements.action_vn_dynamic_report` });
await sleep(3000);
await waitIdle();
const first = await evaluate(`({
    title: document.querySelector('.o_vn_sheet .fs-4')?.innerText,
    rows: document.querySelectorAll('.o_vn_table tbody tr').length,
    total280: [...document.querySelectorAll('.o_vn_table tbody tr')].find(r => r.children[1].innerText === '280')?.children[3].innerText,
    total440: [...document.querySelectorAll('.o_vn_table tbody tr')].find(r => r.children[1].innerText === '440')?.children[3].innerText,
})`);
await shot("ui_1_b01.png");

// IFRS statements: switch report, no button press; then print.
const pick = async (label, value, byText = false) => {
    await evaluate(`(() => {
        const labels = [...document.querySelectorAll('.o_control_panel label')];
        const select = labels.find(l => l.innerText.trim() === ${JSON.stringify(label)}).parentElement.querySelector('select');
        select.value = ${byText} ? [...select.options].find(o => o.text.startsWith(${JSON.stringify(value)})).value : ${JSON.stringify(value)};
        select.dispatchEvent(new Event('change'));
    })()`);
    await sleep(1200);
    await waitIdle();
};
const groups = await evaluate(`[...document.querySelectorAll('.o_control_panel optgroup')].map(g => g.label + ': ' + g.children.length)`);
await pick("Báo cáo", "IFRS - Báo cáo tình hình tài chính hợp nhất", true);
const second = await evaluate(`({
    groups: ${JSON.stringify("")} || null,
    title: document.querySelector('.o_vn_sheet .fs-4')?.innerText,
    rows: [...document.querySelectorAll('.o_vn_table tbody tr')].slice(0, 6).map(r => r.children[0].innerText + ' = ' + r.children[r.children.length - 2].innerText),
    codeColumn: document.querySelectorAll('.o_vn_table thead th').length,
})`);
await shot("ui_ifrs_sfp_c.png");
await pick("Báo cáo", "IFRS - Báo cáo lãi lỗ và thu nhập toàn diện khác hợp nhất", true);
await shot("ui_ifrs_pl_c.png");
await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: outDir });
await evaluate(`[...document.querySelectorAll('.o_control_panel button')].find(b => b.innerText.includes('In PDF')).click()`);
await sleep(10000);
second.groups = groups;
const drill = {};
console.log(JSON.stringify({ first, second, drill, errors }, null, 2));
ws.close();
chrome.kill();
process.exit(0);
