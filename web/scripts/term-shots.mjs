// Renders each terminal log as a Git Bash screenshot for the written test report.
//   node scripts/term-shots.mjs <logs dir> <png dir>
// The frame, prompt and colours copy the project's own terminal (Git Bash in VS Code) so the
// report shows what the run looked like. Long logs keep their head and tail, with the middle
// elided, so the verdict stays in frame.
import { chromium } from "@playwright/test";
import { mkdirSync, readdirSync, readFileSync } from "node:fs";
import { basename, join } from "node:path";

const [src, dst] = process.argv.slice(2);
mkdirSync(dst, { recursive: true });
const HEAD = 40;
const TAIL = 45;
const USER = process.env.TERM_USER ?? "Bimsara@DESKTOP-GDRSKBQ";
const CWD = process.env.TERM_CWD ?? "/d/DSEP22/v3";

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
// eslint-disable-next-line no-control-regex
const plain = (s) => s.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/\r/g, "");
const tone = (line) =>
  /\b(FAIL|FAILED|ERROR|Error|failed|Traceback)\b|✗|✘/.test(line) ? "bad"
    : /\b(PASS|PASSED|passed|OK|ok)\b|✓|✔/.test(line) ? "good"
      : /\b(WARN|Warning|warning|skipped|SKIPPED)\b/.test(line) ? "warn" : "";

const prompt = (command, cursor = false) => `
  <div class="line"><span class="user">${esc(USER)}</span> <span class="mingw">MINGW64</span> <span class="path">${esc(CWD)}</span></div>
  <div class="line"><span class="sign">$</span> ${esc(command)}${cursor ? '<span class="cursor"></span>' : ""}</div>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1180, height: 200 }, deviceScaleFactor: 1.5 });
for (const file of readdirSync(src).filter((f) => f.endsWith(".log")).sort()) {
  const name = basename(file, ".log");
  let lines = plain(readFileSync(join(src, file), "utf8")).split("\n");
  // test-plan.sh writes "== <step>: <command>" first; that is the command the prompt shows.
  let command = `bash scripts/test-plan.sh   # ${name}`;
  if (lines[0]?.startsWith("== ")) {
    command = lines[0].replace(/^==\s*[^:]+:\s*/, "");
    lines = lines.slice(1);
  } else if (lines[0]?.startsWith("$ ")) {
    command = lines[0].slice(2);
    lines = lines.slice(1);
  }
  if (lines.length > HEAD + TAIL + 1) {
    lines = [...lines.slice(0, HEAD), `... ${lines.length - HEAD - TAIL} lines omitted, full log: ${file} ...`, ...lines.slice(-TAIL)];
  }
  while (lines.length && !lines.at(-1).trim()) lines.pop();
  const body = lines.map((l) => `<div class="line ${tone(l)}">${esc(l) || " "}</div>`).join("");
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    :root { --fg:#CCCCCC; --bg:#1E1E1E; --chrome:#181818; }
    body { margin:0; background:var(--bg); color:var(--fg);
           font:12.5px/1.45 "Cascadia Mono","Consolas","DejaVu Sans Mono",monospace; }
    .tabs { display:flex; gap:18px; align-items:center; padding:7px 14px 0; background:var(--chrome);
            border-bottom:1px solid #2B2B2B; font:11.5px system-ui,"Segoe UI",sans-serif; color:#8B8B8B; }
    .tabs span { padding-bottom:6px; }
    .tabs .on { color:#E7E7E7; border-bottom:1px solid #0078D4; }
    .tabs .right { margin-left:auto; color:#CCCCCC; display:flex; align-items:center; gap:6px; }
    .tabs .right::before { content:""; width:8px; height:8px; border-radius:2px; background:#C5C5C5; }
    .screen { padding:10px 14px 14px; }
    .line { white-space:pre-wrap; word-break:break-word; min-height:1.45em; }
    .user { color:#23D18B; font-weight:600; }
    .mingw { color:#E7E7E7; }
    .path { color:#B267E6; font-weight:600; }
    .sign { color:#CCCCCC; }
    .good { color:#23D18B; } .bad { color:#F14C4C; } .warn { color:#E5E510; }
    .cursor { display:inline-block; width:7px; height:1.05em; background:#CCCCCC; vertical-align:text-bottom; }
  </style></head><body>
    <div class="tabs"><span>Problems</span><span>Debug Console</span><span class="on">Terminal</span><span>Ports</span><span class="right">bash</span></div>
    <div class="screen">${prompt(command)}${body}
      ${prompt("", true)}
    </div></body></html>`);
  await page.screenshot({ path: join(dst, `${name}.png`), fullPage: true });
}
await browser.close();
