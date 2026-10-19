// Print an HTML file to PDF with headless Chrome once its Mermaid diagrams are drawn.
// Usage: node print_pdf.mjs <input.html> <output.pdf>   (CHROME env var overrides the browser path)
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [input, output] = process.argv.slice(2);
const CHROME = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "print-pdf-"));

const chrome = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run", "about:blank",
]);
let target;
for (let i = 0; i < 60 && !target; i++) {
    await sleep(250);
    try {
        target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page");
    } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let nextId = 1;
const pending = new Map();
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
    }
};
const send = (method, params = {}) =>
    new Promise((res) => {
        const id = nextId++;
        pending.set(id, res);
        ws.send(JSON.stringify({ id, method, params }));
    });

await send("Page.enable");
await send("Page.navigate", { url: pathToFileURL(resolve(input)).href });
let ready = false;
for (let i = 0; i < 120 && !ready; i++) {
    await sleep(500);
    const res = await send("Runtime.evaluate", { expression: "document.body && document.body.dataset.diagrams", returnByValue: true });
    ready = res.result?.result?.value === "ready";
}
if (!ready) {
    console.error("Mermaid diagrams did not finish rendering (network access to cdn.jsdelivr.net needed).");
    process.exitCode = 1;
}
const pdf = await send("Page.printToPDF", {
    printBackground: true,
    preferCSSPageSize: true,
    displayHeaderFooter: true,
    headerTemplate: "<div></div>",
    footerTemplate:
        "<div style='font-size:8px;width:100%;text-align:center;color:#7b8794;font-family:Segoe UI,Arial'>" +
        "Kế toán VAS (Thông tư 99) trên Odoo 19 — trang <span class='pageNumber'></span>/<span class='totalPages'></span></div>",
});
writeFileSync(output, Buffer.from(pdf.result.data, "base64"));
ws.close();
chrome.kill();
await sleep(500);
try {
    rmSync(profile, { recursive: true, force: true });
} catch {}
