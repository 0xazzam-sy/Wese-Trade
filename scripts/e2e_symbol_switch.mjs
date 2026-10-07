#!/usr/bin/env node
/**
 * Regression E2E for the v1.0.0 blank-chart / stale-context bugs (packaged-style app:
 * backend in desktop mode serving the production build, real OKX data).
 *
 *   node scripts/e2e_symbol_switch.mjs --url http://127.0.0.1:PORT [--out dir] [--viewport 1920x1080]
 *
 * 1. Reported bug: BTC (tens of thousands) → a low-price symbol picked in the market list.
 *    The new candles must be loaded AND inside the visible price range (no BTC scale left
 *    behind, no blank chart) — also after the user dragged/zoomed the price axis.
 * 2. Context invariant: chart header, candles, analysis panel and signal status always
 *    describe the same symbol/timeframe.
 * 3. Rapid switching on both charts (symbols × timeframes) ends consistent.
 *
 * Chart truth comes from read-only data attributes the chart writes on its container
 * (data-price-range = visible price range, data-last-close, data-bars).
 */
import { execSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const args = Object.fromEntries(
  process.argv
    .slice(2)
    .reduce(
      (acc, v, i, a) =>
        v.startsWith("--") ? [...acc, [v.slice(2), a[i + 1]]] : acc,
      [],
    ),
);
const BASE = args.url ?? "http://127.0.0.1:8765";
const OUT = args.out ?? "e2e-switch";
mkdirSync(OUT, { recursive: true });
const require = createRequire(import.meta.url);
const pw = require(
  process.env.PLAYWRIGHT_MODULE ??
    path.join(execSync("npm root -g").toString().trim(), "playwright"),
);

const results = [];
function check(name, ok, detail = "") {
  results.push([name, ok]);
  console.log(
    `[${ok ? "PASS" : "FAIL"}] ${name}${detail ? " - " + detail : ""}`,
  );
}

const browser = await pw.chromium.launch(
  process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH }
    : process.env.CHROMIUM_CHANNEL
      ? { channel: process.env.CHROMIUM_CHANNEL }
      : {},
);
const [vw, vh] = (args.viewport ?? "1366x768").split("x").map(Number);
const context = await browser.newContext({
  viewport: { width: vw, height: vh },
  locale: "ar",
});
const page = await context.newPage();
const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push(String(e)));

const setup = await page.request.get(`${BASE}/api/v1/auth/setup`);
const password =
  process.env.E2E_ADMIN_PASSWORD ?? randomBytes(18).toString("base64url");
if ((await setup.json()).needs_setup) {
  await page.request.post(`${BASE}/api/v1/auth/setup`, {
    data: { username: "e2e_admin", password },
  });
} else if (process.env.E2E_ADMIN_PASSWORD) {
  await page.request.post(`${BASE}/api/v1/auth/login`, {
    data: { username: "e2e_admin", password },
  });
}

const panel = (id) => page.locator(`section[data-chart="${id}"]`);

/** What chart `id` really shows: selection, load state, candles, visible price range. */
async function chartTruth(id) {
  return page.evaluate((chartId) => {
    const section = document.querySelector(`section[data-chart="${chartId}"]`);
    const box = section?.querySelector("[data-price-range]");
    const [from, to] = (box?.dataset.priceRange ?? ":").split(":").map(Number);
    return {
      symbol: section?.dataset.symbol,
      timeframe: section?.dataset.timeframe,
      load: section?.dataset.load,
      analysis: section?.dataset.analysis,
      analysisSymbol: section?.dataset.analysisSymbol,
      header: section
        ?.querySelector('[data-testid="chart-symbol"]')
        ?.textContent?.trim(),
      bars: Number(box?.dataset.bars ?? 0),
      last: Number(box?.dataset.lastClose ?? NaN),
      from,
      to,
    };
  }, id);
}

async function settle(id, symbol, timeframe) {
  await page.waitForFunction(
    ([chartId, sym, tf]) => {
      const s = document.querySelector(`section[data-chart="${chartId}"]`);
      return (
        s?.dataset.symbol === sym &&
        s.dataset.timeframe === tf &&
        s.dataset.load === "ready"
      );
    },
    [id, symbol, timeframe],
    { timeout: 90_000 },
  );
  await page.waitForTimeout(1600); // diagnostics refresh every 500 ms
  return chartTruth(id);
}

function inRange(t) {
  return (
    t.bars > 0 && Number.isFinite(t.last) && t.last >= t.from && t.last <= t.to
  );
}

async function pickFromMarketList(symbol) {
  const search = page.getByPlaceholder(/BTC, ETH/);
  await search.fill(symbol.replace("USDT", ""));
  await page
    .locator(`button[role="listitem"]`, { hasText: symbol.replace("USDT", "") })
    .first()
    .click();
  await search.fill("");
}

async function dragPriceAxis(id) {
  const box = await panel(id).locator("[data-price-range]").boundingBox();
  if (!box) return;
  const x = box.x + box.width - 25; // right price axis
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y - 120, { steps: 8 });
  await page.mouse.up();
  await page.mouse.move(5, 5);
}

await page.goto(BASE, { waitUntil: "networkidle" });
const start = await settle("primary", "BTCUSDT", "15m");
check(
  "BTC loaded with a BTC-scale range",
  inRange(start),
  `last ${start.last} in [${start.from}, ${start.to}]`,
);

// --- 1a. reported bug: BTC → NEAR from the market list -----------------------------------
await pickFromMarketList("NEARUSDT");
let t = await settle("primary", "NEARUSDT", "15m");
check("BTC → NEAR: candles loaded", t.bars > 0, `${t.bars} bars`);
check(
  "BTC → NEAR: price scale follows NEAR (no BTC scale)",
  inRange(t),
  `last ${t.last} in [${t.from}, ${t.to}]`,
);
await page.screenshot({ path: path.join(OUT, "near-after-btc.png") });

// --- 1b. same after the user dragged the price axis (autoscale switched off) -------------
for (const [from, to] of [
  ["BTCUSDT", "DOGEUSDT"],
  ["ETHUSDT", "PEPEUSDT"],
  ["PEPEUSDT", "BTCUSDT"],
  ["SOLUSDT", "XRPUSDT"],
]) {
  await pickFromMarketList(from);
  await settle("primary", from, "15m");
  await dragPriceAxis("primary");
  await pickFromMarketList(to);
  t = await settle("primary", to, "15m");
  check(
    `${from} (axis dragged) → ${to}: candles visible in price range`,
    inRange(t),
    `last ${t.last} in [${t.from}, ${t.to}]`,
  );
}

// --- 2. context invariant: header / analysis / panel all describe the chart -----------------
async function contextConsistent(id) {
  const c = await chartTruth(id);
  const header = c.header === c.symbol;
  const analysis =
    c.analysis === "none" || c.analysisSymbol === `${c.symbol}|${c.timeframe}`;
  return { ok: header && analysis, c };
}
for (const id of ["primary", "secondary"]) {
  const { ok, c } = await contextConsistent(id);
  check(
    `${id}: header + analysis match the chart context`,
    ok,
    JSON.stringify(c),
  );
}
const panelContext = await page
  .getByTestId("analysis-context")
  .textContent()
  .catch(() => null);
const focused = await page.evaluate(() =>
  document
    .querySelector('[data-testid="analysis-context"]')
    ?.getAttribute("data-chart"),
);
const fc = await chartTruth(focused ?? "primary");
check(
  "analysis panel describes exactly the focused chart",
  panelContext?.includes(fc.symbol ?? "?") === true,
  `${panelContext ?? "missing"} vs ${fc.symbol}`,
);

// --- 3. rapid switching on both charts (no waiting between clicks) -------------------------
const symbols = [
  "BTCUSDT",
  "ETHUSDT",
  "DOGEUSDT",
  "NEARUSDT",
  "PEPEUSDT",
  "BTCUSDT",
];
const tfs = ["5m", "15m", "1h", "1m"];
for (let i = 0; i < symbols.length; i++) {
  await pickFromMarketList(symbols[i]);
  await panel("secondary")
    .locator(`[role="radio"][title="${tfs[i % tfs.length]}"]`)
    .click();
}
const finalPrimary = await settle("primary", "BTCUSDT", "15m");
check(
  "rapid switch: final primary chart is BTC with BTC candles in range",
  inRange(finalPrimary),
  JSON.stringify(finalPrimary),
);
const secTf = tfs[(symbols.length - 1) % tfs.length];
const sec = await chartTruth("secondary");
const finalSecondary = await settle("secondary", sec.symbol, secTf);
check(
  "rapid switch: secondary chart consistent",
  inRange(finalSecondary),
  JSON.stringify(finalSecondary),
);
for (const id of ["primary", "secondary"]) {
  const { ok, c } = await contextConsistent(id);
  check(`rapid switch: ${id} context consistent`, ok, JSON.stringify(c));
}
await page.screenshot({ path: path.join(OUT, "after-rapid-switch.png") });

check(
  "no page errors",
  consoleErrors.length === 0,
  consoleErrors.slice(0, 2).join(" | "),
);
await browser.close();
const failed = results.filter(([, ok]) => !ok);
console.log(
  `== symbol switch E2E: ${results.length - failed.length}/${results.length} checks passed`,
);
process.exit(failed.length ? 1 : 0);
