// Renders each terminal log as a terminal-style PNG for the written test report.
//   node scripts/term-shots.mjs <logs dir> <png dir>
// Long logs keep their head and tail, with the middle elided, so the verdict stays in frame.
import { chromium } from "@playwright/test";
import { mkdirSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";

const [src, dst] = process.argv.slice(2);
mkdirSync(dst, { recursive: true });
const HEAD = 40;
const TAIL = 45;
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
// eslint-disable-next-line no-control-regex
const plain = (s) => s.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/\r/g, "");
const tone = (line) =>
  /\b(FAIL|FAILED|ERROR|Error|failed)\b|✗|✘/.test(line) ? "bad"
    : /\b(PASS|PASSED|passed|OK|ok)\b|✓|✔/.test(line) ? "good" : "";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 400 }, deviceScaleFactor: 1.5 });
for (const file of readdirSync(src).filter((f) => f.endsWith(".log")).sort()) {
  let lines = plain(readFileSync(join(src, file), "utf8")).split("\n");
  if (lines.length > HEAD + TAIL + 1) {
    lines = [...lines.slice(0, HEAD), `... ${lines.length - HEAD - TAIL} lines omitted, full log: ${file} ...`, ...lines.slice(-TAIL)];
  }
  const body = lines.map((l) => `<div class="${tone(l)}">${esc(l) || " "}</div>`).join("");
  await page.setContent(`<!doctype html><html><head><style>
    body{margin:0;background:#1e1e2e;font:13px/1.45 Consolas,"Cascadia Mono",monospace;color:#cdd6f4}
    .bar{background:#313244;padding:8px 14px;color:#a6adc8;font:12px system-ui}
    .bar b{color:#cdd6f4}.dots{display:inline-block;margin-right:10px;color:#f38ba8;letter-spacing:3px}
    pre{margin:0;padding:12px 16px;white-space:pre-wrap;word-break:break-all}
    .good{color:#a6e3a1}.bad{color:#f38ba8}
  </style></head><body><div class="bar"><span class="dots">●●●</span><b>${esc(basename(file, ".log"))}</b> · Lanka Link v3 test run</div><pre>${body}</pre></body></html>`);
  await page.screenshot({ path: join(dst, file.replace(/\.log$/, ".png")), fullPage: true });
}
await browser.close();
