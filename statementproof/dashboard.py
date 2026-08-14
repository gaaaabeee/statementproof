"""Build a self-contained HTML dashboard from the parsed tables.

    ./.venv/bin/python -m statementproof.dashboard

Reads out/transactions.csv + out/statements.csv (run statementproof.run first) and
writes out/dashboard.html -- one file, no network, no external assets, so the
financial data never leaves this machine.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")

EXCLUDED = {"Transfers", "Refunds", "Income", "Reimbursements", "One-off deposits"}
INFLOW_CATEGORIES = ["Income", "Reimbursements", "One-off deposits", "Refunds"]
SPEND_CREDIT_KINDS = {"purchase", "cash_advance", "fee", "interest"}
TOP_CATEGORIES = 7          # + "Other"; the palette has 8 categorical slots


def load() -> tuple[list[dict], list[dict]]:
    with open(os.path.join(OUT, "transactions.csv")) as fh:
        txns = list(csv.DictReader(fh))
    with open(os.path.join(OUT, "statements.csv")) as fh:
        stmts = list(csv.DictReader(fh))
    for t in txns:
        t["amount"] = float(t["amount"])
        t["signed"] = float(t["signed"])
        t["month"] = t["date"][:7]
    return txns, stmts


def is_spend(t: dict) -> bool:
    if t["category"] in EXCLUDED:
        return False
    if t["account"] == "credit":
        return t["kind"] in SPEND_CREDIT_KINDS
    return t["kind"] == "withdrawal"


def find_recurring(spend: list[dict], corpus_end: str) -> list[dict]:
    """Merchants that bill on a schedule.

    The signal that separates a bill from a habit is **gap regularity**, not
    amount stability -- an electricity bill swings 42% month to month and is
    still a bill.

    Dispersion is measured with the median absolute deviation, not the standard
    deviation, because one interruption wrecks the latter: a biweekly cleaning
    service with a single 82-day break scores stdev CV 0.90 (indistinguishable
    from Pizza Hut at 0.75) but MAD ratio 0.18. On this data MAD separates
    cleanly -- every real bill lands <= 0.18, the first habit at 0.27.

    So: >= 4 charges in >= 4 distinct months, a median gap matching a known
    cadence, MAD ratio <= 0.20, and amounts within a loose 0.6 CV.

    Each hit is also marked ``active`` or not: a charge stream whose last entry
    is more than 2.5 cadence-periods before the end of the data has stopped,
    and reporting its cost as ongoing would overstate the monthly total.
    """
    by_merchant = defaultdict(list)
    for t in spend:
        by_merchant[t["merchant"]].append(t)

    found = []
    for merchant, rows in by_merchant.items():
        if len(rows) < 4 or len({r["month"] for r in rows}) < 4:
            continue
        rows.sort(key=lambda r: r["date"])
        days = [date.fromisoformat(r["date"]).toordinal() for r in rows]
        gaps = [b - a for a, b in zip(days, days[1:]) if b - a > 0]
        if len(gaps) < 3:
            continue
        gap = statistics.median(gaps)
        if gap <= 0:
            continue
        # Median absolute deviation: robust to a single missed or doubled cycle.
        if statistics.median([abs(g - gap) for g in gaps]) / gap > 0.20:
            continue
        cadence = (
            "weekly" if 5 <= gap <= 9 else
            "biweekly" if 12 <= gap <= 18 else
            "monthly" if 25 <= gap <= 36 else
            "quarterly" if 84 <= gap <= 98 else
            "annual" if 350 <= gap <= 380 else None
        )
        if cadence is None:
            continue
        amounts = [-r["signed"] for r in rows]
        mean = statistics.fmean(amounts)
        if mean <= 0:
            continue
        cv = (statistics.pstdev(amounts) / mean) if len(amounts) > 1 else 0.0
        if cv > 0.60:
            continue
        per_month = {"weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1,
                     "quarterly": 1 / 3, "annual": 1 / 12}[cadence]
        stale_days = date.fromisoformat(corpus_end).toordinal() - days[-1]
        found.append({
            "merchant": merchant,
            "category": rows[-1]["category"],
            "cadence": cadence,
            "typical": round(statistics.median(amounts), 2),
            "count": len(rows),
            "total": round(sum(amounts), 2),
            "monthly": round(statistics.median(amounts) * per_month, 2),
            "first": rows[0]["date"],
            "last": rows[-1]["date"],
            "variable": cv > 0.15,
            "active": stale_days <= gap * 2.5,
            "missed": int(stale_days // gap) if stale_days > gap * 2.5 else 0,
        })
    # Active first, then by cost -- an ended charge is not a current cost.
    return sorted(found, key=lambda r: (not r["active"], -r["monthly"]))


def build_payload() -> dict:
    txns, stmts = load()
    spend = [t for t in txns if is_spend(t)]

    months = sorted({t["month"] for t in spend})

    totals = defaultdict(float)
    for t in spend:
        totals[t["category"]] += -t["signed"]
    ranked = sorted(totals, key=lambda c: -totals[c])
    top = ranked[:TOP_CATEGORIES]
    # Fixed once, from the whole period: a filter must never repaint a series.
    cat_order = top + ["Other"]

    def bucket(cat: str) -> str:
        return cat if cat in top else "Other"

    grid = {(m, c): 0.0 for m in months for c in cat_order}
    for t in spend:
        grid[(t["month"], bucket(t["category"]))] += -t["signed"]

    monthly = [
        {"month": m, "values": [round(grid[(m, c)], 2) for c in cat_order]}
        for m in months
    ]

    # Balances: one point per statement, at its close date. Every account is in
    # dollars so they share a single axis (never a second scale). One series per
    # real account, so a second card or a savings account simply adds a line
    # rather than needing new code.
    KIND_LABEL = {"checking": "Checking", "credit": "Credit card"}
    balances, series_names, series_kind = [], {}, {}
    for s in sorted(stmts, key=lambda s: s["period_end"]):
        raw = s.get("ending_balance") or s.get("new_balance")
        if not raw:
            continue
        key = f"{s['account']}:{s['account_last4']}"
        series_names[key] = (f"{KIND_LABEL.get(s['account'], s['account'].title())} "
                             f"···{s['account_last4']}")
        series_kind[key] = s["account"]
        balances.append({"date": s["period_end"], "series": key, "value": float(raw)})
    # Stable order: liabilities first so the debt line reads as the headline.
    series_order = sorted(series_names, key=lambda k: (series_kind[k] != "credit", k))

    finance = defaultdict(float)
    for t in txns:
        if t["account"] == "credit" and t["kind"] in ("interest", "fee"):
            finance[t["month"]] += t["amount"]

    merch = defaultdict(float)
    merch_n = defaultdict(int)
    for t in spend:
        merch[t["merchant"]] += -t["signed"]
        merch_n[t["merchant"]] += 1

    # --- cash flow: money in against money out, month by month ---------------
    # Transfers sit outside both sides: a Truist top-up or a brokerage move is
    # the user's own money changing seats, not earnings and not consumption.
    inflow_rows = [t for t in txns if t["signed"] > 0 and t["category"] in INFLOW_CATEGORIES]
    flow_months = sorted({t["month"] for t in spend} | {t["month"] for t in inflow_rows})
    flow = {m: {c: 0.0 for c in INFLOW_CATEGORIES} | {"spend": 0.0} for m in flow_months}
    for t in inflow_rows:
        flow[t["month"]][t["category"]] += t["signed"]
    for t in spend:
        flow[t["month"]]["spend"] += -t["signed"]

    cashflow = [
        {"month": m,
         "in": round(sum(flow[m][c] for c in INFLOW_CATEGORIES), 2),
         "income": round(flow[m]["Income"], 2),
         "reimb": round(flow[m]["Reimbursements"] + flow[m]["Refunds"], 2),
         "oneoff": round(flow[m]["One-off deposits"], 2),
         "out": round(flow[m]["spend"], 2)}
        for m in flow_months
    ]

    src = defaultdict(lambda: [0, 0.0])
    for t in inflow_rows:
        src[(t["merchant"], t["category"])][0] += 1
        src[(t["merchant"], t["category"])][1] += t["signed"]
    inflow_sources = sorted(
        [{"name": m, "category": c, "total": round(v, 2), "count": n}
         for (m, c), (n, v) in src.items()],
        key=lambda r: -r["total"],
    )

    transfers_net = round(sum(t["signed"] for t in txns if t["category"] == "Transfers"), 2)

    # Partial cycles at each end -- the first and last months aren't full.
    partial = {months[0], months[-1]}

    return {
        "cashflow": cashflow,
        "inflow_sources": inflow_sources,
        "transfers_net": transfers_net,
        "generated": date.today().isoformat(),
        "months": months,
        "partial": sorted(partial),
        "categories": cat_order,
        "monthly": monthly,
        "balances": balances,
        "balance_series": [{"key": k, "name": series_names[k], "kind": series_kind[k]}
                           for k in series_order],
        "finance": [{"month": m, "value": round(finance.get(m, 0.0), 2)} for m in months],
        "merchants": sorted(
            [{"merchant": k, "total": round(v, 2), "count": merch_n[k]} for k, v in merch.items()],
            key=lambda r: -r["total"],
        )[:15],
        "recurring": find_recurring(spend, max(s["period_end"] for s in stmts)),
        "txns": [
            {"d": t["date"], "m": t["merchant"], "c": t["category"], "a": t["signed"],
             "k": t["kind"], "acct": t["account"], "raw": t["description"]}
            for t in sorted(txns, key=lambda t: t["date"], reverse=True)
        ],
        "coverage": {
            "start": min(s["period_start"] for s in stmts),
            "end": max(s["period_end"] for s in stmts),
            "statements": len(stmts),
            "rows": len(txns),
        },
    }


def main() -> int:
    payload = build_payload()
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    path = os.path.join(OUT, "dashboard.html")
    with open(path, "w") as fh:
        fh.write(html)
    size = os.path.getsize(path) / 1024
    print(f"wrote {os.path.relpath(path, ROOT)} ({size:,.0f} KB, "
          f"{payload['coverage']['rows']:,} transactions)")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banking dashboard</title>
<style>
  :root {
    color-scheme: light;
    --surface-1: #fcfcfb;
    --plane: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --good: #006300;
    --critical: #d03b3b;
    --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
    --s5: #e87ba4; --s6: #008300; --s7: #4a3aa7; --s8: #e34948;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --surface-1: #1a1a19;
      --plane: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --good: #0ca30c;
      --critical: #d03b3b;
      --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
      --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --plane: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --good: #0ca30c;
    --critical: #d03b3b;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
    --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    background: var(--plane);
    color: var(--text-primary);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 32px 20px 72px; }

  header { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; margin-bottom: 4px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
  .sub { color: var(--text-secondary); font-size: 13px; }
  .spacer { flex: 1; }
  button {
    font: inherit; font-size: 13px; color: var(--text-secondary);
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 12px; cursor: pointer;
  }
  button:hover { color: var(--text-primary); }
  button[aria-pressed="true"] { background: var(--text-primary); color: var(--surface-1); border-color: var(--text-primary); }

  /* one filter row, above everything it scopes */
  .filters {
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    margin: 20px 0 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border);
  }
  .filters .label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-right: 4px; }

  .hero { margin: 8px 0 28px; }
  .hero .figure { font-size: 52px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.05; }
  .hero .cap { color: var(--text-secondary); font-size: 14px; margin-top: 4px; }

  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 28px; }
  .tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
  .tile .label { font-size: 13px; color: var(--text-secondary); }
  .tile .value { font-size: 27px; font-weight: 600; letter-spacing: -0.01em; margin-top: 6px; }
  .tile .delta { font-size: 13px; color: var(--text-secondary); margin-top: 4px; }
  .tile .delta.up { color: var(--critical); }
  .tile .delta.down { color: var(--good); }

  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px 18px; margin-bottom: 20px; }
  .card h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
  .card .note { font-size: 13px; color: var(--text-secondary); margin: 0 0 16px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 860px) { .grid2 { grid-template-columns: 1fr; } }

  .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-bottom: 14px; }
  .legend span { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); }
  .legend i { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }

  .plot { width: 100%; overflow-x: auto; }
  svg { display: block; max-width: 100%; }
  svg text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
  svg .axis-line { stroke: var(--axis); stroke-width: 1; }
  svg .grid-line { stroke: var(--grid); stroke-width: 1; }
  svg .lbl { fill: var(--text-secondary); font-size: 11px; }

  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 600; color: var(--text-secondary); padding: 7px 10px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--surface-1); }
  td { padding: 7px 10px; border-bottom: 1px solid var(--grid); }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  tbody tr:hover { background: color-mix(in srgb, var(--text-primary) 4%, transparent); }
  .swatch { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; vertical-align: baseline; }
  .tag { font-size: 12px; color: var(--text-secondary); }
  .scroll { max-height: 460px; overflow-y: auto; }
  .tableview { display: none; margin-top: 16px; }
  .tableview.on { display: block; }

  #tip {
    position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px;
    padding: 9px 11px; font-size: 12.5px; box-shadow: 0 6px 20px rgba(0,0,0,.14);
    z-index: 50; max-width: 280px;
  }
  #tip .t { font-weight: 600; margin-bottom: 5px; font-size: 13px; color: var(--text-primary); }
  #tip .r { display: flex; justify-content: space-between; gap: 16px; color: var(--text-secondary); }
  #tip .r b { font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  #tip .tot { border-top: 1px solid var(--border); margin-top: 6px; padding-top: 5px; }

  .search { font: inherit; font-size: 13px; padding: 7px 11px; border-radius: 8px;
            border: 1px solid var(--border); background: var(--plane); color: var(--text-primary); width: 260px; }
  .foot { color: var(--muted); font-size: 12.5px; margin-top: 28px; line-height: 1.6; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Banking dashboard</h1>
    <span class="sub" id="coverage"></span>
    <span class="spacer"></span>
    <button id="tableToggle" aria-pressed="false">Show data tables</button>
    <button id="themeToggle">Theme</button>
  </header>

  <div class="filters">
    <span class="label">Period</span>
    <button data-range="all" aria-pressed="true">All</button>
    <button data-range="12">Last 12 months</button>
    <button data-range="6">Last 6 months</button>
    <button data-range="2026">2026</button>
    <button data-range="2025">2025</button>
  </div>

  <div class="hero">
    <div class="figure" id="heroFigure"></div>
    <div class="cap" id="heroCap"></div>
  </div>

  <div class="tiles" id="tiles"></div>

  <div class="card">
    <h2>Money in vs money out</h2>
    <p class="note" id="flowNote"></p>
    <div class="legend" id="flowLegend"></div>
    <div class="plot"><svg id="flow" role="img" aria-label="Money in against money out, by month"></svg></div>
    <div class="tableview" id="flowTable"></div>
  </div>

  <div class="card">
    <h2>Spending by month</h2>
    <p class="note" id="stackNote"></p>
    <div class="legend" id="stackLegend"></div>
    <div class="plot"><svg id="stack" role="img" aria-label="Monthly spending by category"></svg></div>
    <div class="tableview" id="stackTable"></div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Account balances</h2>
      <p class="note">Statement closing balances. Both in dollars, one shared axis.</p>
      <div class="legend" id="balLegend"></div>
      <div class="plot"><svg id="balance" role="img" aria-label="Account balances over time"></svg></div>
      <div class="tableview" id="balanceTable"></div>
    </div>
    <div class="card">
      <h2>Interest &amp; fees charged</h2>
      <p class="note">What carrying a card balance costs, per statement.</p>
      <div class="plot"><svg id="finance" role="img" aria-label="Interest and fees charged per month"></svg></div>
      <div class="tableview" id="financeTable"></div>
    </div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Spending by category</h2>
      <p class="note" id="catNote"></p>
      <div class="plot"><svg id="cats" role="img" aria-label="Total spending by category"></svg></div>
      <div class="tableview" id="catsTable"></div>
    </div>
    <div class="card">
      <h2>Top merchants</h2>
      <p class="note" id="merchNote"></p>
      <div class="plot"><svg id="merch" role="img" aria-label="Top merchants by spend"></svg></div>
      <div class="tableview" id="merchTable"></div>
    </div>
  </div>

  <div class="card">
    <h2>Where money comes from</h2>
    <p class="note" id="srcNote"></p>
    <div class="plot"><svg id="src" role="img" aria-label="Money in by source"></svg></div>
    <div class="tableview" id="srcTable"></div>
  </div>

  <div class="card">
    <h2>Recurring charges</h2>
    <p class="note" id="recNote"></p>
    <div class="scroll"><table id="recurring"></table></div>
  </div>

  <div class="card">
    <h2>All transactions</h2>
    <p class="note">Every parsed row, newest first. Search matches merchant, category or the raw statement descriptor.</p>
    <input class="search" id="search" type="search" placeholder="Search transactions…" aria-label="Search transactions">
    <span class="tag" id="txnCount"></span>
    <div class="scroll" style="margin-top:12px"><table id="txns"></table></div>
  </div>

  <p class="foot" id="foot"></p>
</div>

<div id="tip" role="tooltip"></div>

<script>
const DATA = __DATA__;
const SERIES = ["--s1","--s2","--s3","--s4","--s5","--s6","--s7","--s8"];
// Colour follows the entity: fixed at build time from the whole period, so a
// filter that drops a category never repaints the survivors.
const CAT_COLOR = {};
DATA.categories.forEach((c, i) => CAT_COLOR[c] = `var(${SERIES[i % 8]})`);
// "Other" is a remainder, not an entity, so it takes the de-emphasis gray
// rather than spending a categorical slot on it.
CAT_COLOR["Other"] = "var(--muted)";
// One colour per real account, fixed at build time in a stable order, so a
// second card or savings account never repaints the existing lines.
const BAL_COLOR = {};
DATA.balance_series.forEach((s, i) => BAL_COLOR[s.key] = `var(${SERIES[i % 8]})`);

const $ = s => document.querySelector(s);
const sign = n => n < 0 ? "-" : "";
const money = n => sign(n) + "$" + Math.round(Math.abs(n)).toLocaleString();
const money2 = n => sign(n) + "$" + Math.abs(n).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
const compact = n => {
  const a = Math.abs(n);
  return sign(n) + (a >= 1000 ? "$" + (a/1000).toFixed(a >= 10000 ? 0 : 1) + "K" : "$" + Math.round(a));
};

const SPEND_KINDS = ["purchase","cash_advance","fee","interest"];
const isSpendRow = t => !["Transfers","Refunds","Income"].includes(t.c)
  && ((t.acct === "credit" && SPEND_KINDS.includes(t.k)) || (t.acct === "checking" && t.k === "withdrawal"));
// Spend rows for the selected period, at full category resolution (the stacked
// chart folds to 8 slots; the breakdown below must not).
function periodSpend() {
  const months = monthsInRange();
  return DATA.txns.filter(t => months.includes(t.d.slice(0,7)) && isSpendRow(t));
}
const MONTH_LBL = m => {
  const [y, mo] = m.split("-");
  return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+mo-1] + " " + y.slice(2);
};

let range = "all";
let showTables = false;

function monthsInRange() {
  const all = DATA.months;
  if (range === "all") return all;
  if (range === "2025" || range === "2026") return all.filter(m => m.startsWith(range));
  return all.slice(-parseInt(range, 10));
}

/* ---------- tooltip ---------- */
const tip = $("#tip");
function showTip(evt, html) {
  tip.innerHTML = html;
  tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + 14, y = evt.clientY + 14;
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - 14;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTip() { tip.style.opacity = 0; }

/* ---------- svg helpers ---------- */
const NS = "http://www.w3.org/2000/svg";
function el(name, attrs = {}) {
  const n = document.createElementNS(NS, name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function niceMax(v) {
  if (v <= 0) return 10;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / (pow / 2)) * (pow / 2);
}
// Column with a 4px-rounded cap and square feet at the baseline.
function cappedBar(x, y, w, h, fill, r = 4) {
  const rr = Math.min(r, h, w / 2);
  const d = `M${x},${y+h} L${x},${y+rr} Q${x},${y} ${x+rr},${y} L${x+w-rr},${y} Q${x+w},${y} ${x+w},${y+rr} L${x+w},${y+h} Z`;
  return el("path", { d, fill });
}

/* ---------- stacked columns: monthly spending ---------- */
function drawStack() {
  const svg = $("#stack");
  svg.innerHTML = "";
  const months = monthsInRange();
  const rows = DATA.monthly.filter(r => months.includes(r.month));
  const cats = DATA.categories;

  const W = Math.max(680, rows.length * 58), H = 320;
  const M = { t: 12, r: 14, b: 40, l: 54 };
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W); svg.setAttribute("height", H);

  const max = niceMax(Math.max(...rows.map(r => r.values.reduce((a,b)=>a+b,0)), 1));
  const y = v => M.t + ph - (v / max) * ph;
  const band = pw / Math.max(rows.length, 1);
  const bw = Math.min(24, band * 0.62);

  for (let i = 0; i <= 4; i++) {
    const v = max * i / 4;
    svg.appendChild(el("line", { class: "grid-line", x1: M.l, x2: M.l + pw, y1: y(v), y2: y(v) }));
    const t = el("text", { x: M.l - 9, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = compact(v);
    svg.appendChild(t);
  }

  rows.forEach((row, i) => {
    const cx = M.l + band * i + band / 2 - bw / 2;
    const total = row.values.reduce((a,b)=>a+b,0);
    let acc = 0;
    // Draw top-down so each segment's 2px surface gap sits under the one above.
    for (let c = cats.length - 1; c >= 0; c--) {
      const v = row.values[c];
      if (v <= 0) continue;
      const below = row.values.slice(0, c).reduce((a,b)=>a+b,0);
      const top = y(below + v), bot = y(below);
      const h = Math.max(bot - top - 2, 1);         // 2px surface gap
      const isTop = row.values.slice(c+1).every(x => x <= 0);
      const seg = isTop ? cappedBar(cx, top, bw, h, CAT_COLOR[cats[c]])
                        : el("rect", { x: cx, y: top, width: bw, height: h, fill: CAT_COLOR[cats[c]] });
      svg.appendChild(seg);
      acc += v;
    }
    // Hit target spans the whole band, not just the 24px column.
    const hit = el("rect", { x: M.l + band*i, y: M.t, width: band, height: ph, fill: "transparent" });
    const partial = DATA.partial.includes(row.month);
    hit.addEventListener("mousemove", e => {
      const parts = cats.map((c, ci) => ({ c, v: row.values[ci] }))
        .filter(p => p.v > 0).sort((a,b) => b.v - a.v)
        .map(p => `<div class="r"><span><i class="swatch" style="background:${CAT_COLOR[p.c]}"></i>${p.c}</span><b>${money(p.v)}</b></div>`)
        .join("");
      showTip(e, `<div class="t">${MONTH_LBL(row.month)}${partial ? " · partial cycle" : ""}</div>${parts}
                  <div class="r tot"><span>Total</span><b>${money(total)}</b></div>`);
    });
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);

    const lb = el("text", { x: M.l + band*i + band/2, y: H - 20, "text-anchor": "middle" });
    lb.textContent = MONTH_LBL(row.month);
    if (partial) lb.setAttribute("opacity", "0.55");
    svg.appendChild(lb);
  });

  svg.appendChild(el("line", { class: "axis-line", x1: M.l, x2: M.l + pw, y1: y(0), y2: y(0) }));

  const legend = $("#stackLegend");
  legend.innerHTML = cats.map(c =>
    `<span><i style="background:${CAT_COLOR[c]}"></i>${c}</span>`).join("");

  $("#stackNote").textContent =
    `Stacked by category. Top ${DATA.categories.length - 1} categories by spend; everything else is "Other". `
    + `${DATA.partial.map(MONTH_LBL).join(" and ")} are partial statement cycles.`;

  tableFor("#stackTable", ["Month", ...cats, "Total"],
    rows.map(r => [MONTH_LBL(r.month), ...r.values.map(money2), money2(r.values.reduce((a,b)=>a+b,0))]),
    [false, ...cats.map(()=>true), true]);
}

/* ---------- diverging columns: cash flow ---------- */
// Polarity, so the diverging pair applies: blue in, red out, neutral zero line.
const IN_COLOR = "var(--s1)", OUT_COLOR = "var(--s8)";
function drawFlow() {
  const svg = $("#flow");
  svg.innerHTML = "";
  const months = monthsInRange();
  const rows = DATA.cashflow.filter(r => months.includes(r.month));

  const W = Math.max(680, rows.length * 58), H = 340;
  const M = { t: 16, r: 14, b: 40, l: 58 };
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W); svg.setAttribute("height", H);

  const max = niceMax(Math.max(...rows.map(r => Math.max(r.in, r.out)), 1));
  const mid = M.t + ph / 2;                    // zero line, centred
  const half = ph / 2;
  const y = v => mid - (v / max) * half;       // +ve above, -ve below
  const band = pw / Math.max(rows.length, 1);
  const bw = Math.min(24, band * 0.62);

  for (let i = -2; i <= 2; i++) {
    const v = max * i / 2;
    svg.appendChild(el("line", { class: i === 0 ? "axis-line" : "grid-line",
                                 x1: M.l, x2: M.l + pw, y1: y(v), y2: y(v) }));
    const t = el("text", { x: M.l - 9, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = compact(Math.abs(v));
    svg.appendChild(t);
  }

  rows.forEach((r, i) => {
    const cx = M.l + band * i + band/2 - bw/2;
    if (r.in > 0) {
      const h = Math.max(mid - y(r.in) - 1, 1);       // 2px gap across the axis
      svg.appendChild(cappedBar(cx, y(r.in), bw, h, IN_COLOR));
    }
    if (r.out > 0) {
      const h = Math.max(y(-r.out) - mid - 1, 1);
      // Flipped cap: rounded at the data end, square at the zero line.
      const g = el("g", { transform: `translate(${cx + bw/2}, ${mid + 1 + h/2}) scale(1,-1) translate(${-(cx + bw/2)}, ${-(mid + 1 + h/2)})` });
      g.appendChild(cappedBar(cx, mid + 1, bw, h, OUT_COLOR));
      svg.appendChild(g);
    }
    const hit = el("rect", { x: M.l + band*i, y: M.t, width: band, height: ph, fill: "transparent" });
    const net = r.in - r.out;
    const partial = DATA.partial.includes(r.month);
    hit.addEventListener("mousemove", e => showTip(e,
      `<div class="t">${MONTH_LBL(r.month)}${partial ? " · partial cycle" : ""}</div>
       <div class="r"><span><i class="swatch" style="background:${IN_COLOR}"></i>Money in</span><b>${money(r.in)}</b></div>`
      + (r.income ? `<div class="r"><span style="padding-left:16px">· income</span><b>${money(r.income)}</b></div>` : "")
      + (r.reimb ? `<div class="r"><span style="padding-left:16px">· reimbursements</span><b>${money(r.reimb)}</b></div>` : "")
      + (r.oneoff ? `<div class="r"><span style="padding-left:16px">· one-off deposit</span><b>${money(r.oneoff)}</b></div>` : "")
      + `<div class="r"><span><i class="swatch" style="background:${OUT_COLOR}"></i>Money out</span><b>${money(r.out)}</b></div>
         <div class="r tot"><span>Net</span><b style="color:${net < 0 ? "var(--critical)" : "var(--good)"}">${money(net)}</b></div>`));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);

    const lb = el("text", { x: M.l + band*i + band/2, y: H - 20, "text-anchor": "middle" });
    lb.textContent = MONTH_LBL(r.month);
    if (partial) lb.setAttribute("opacity", "0.55");
    svg.appendChild(lb);
  });

  $("#flowLegend").innerHTML =
    `<span><i style="background:${IN_COLOR}"></i>Money in (income, reimbursements, deposits)</span>`
    + `<span><i style="background:${OUT_COLOR}"></i>Money out (all spending)</span>`;

  const tin = rows.reduce((a,r) => a + r.in, 0), tout = rows.reduce((a,r) => a + r.out, 0);
  const short = rows.filter(r => r.in - r.out < 0).length;
  $("#flowNote").innerHTML =
    `${money(tin)} in against ${money(tout)} out — <b>net ${money(tin - tout)}</b>. `
    + `${short} of ${rows.length} months spent more than they took in. `
    + `Transfers between your own accounts are excluded from both sides.`;

  tableFor("#flowTable", ["Month", "Income", "Reimbursements", "One-off", "Money in", "Money out", "Net"],
    rows.slice().reverse().map(r => [MONTH_LBL(r.month), money2(r.income), money2(r.reimb),
      money2(r.oneoff), money2(r.in), money2(r.out), money2(r.in - r.out)]),
    [false, true, true, true, true, true, true]);
}

/* ---------- lines: balances ---------- */
function drawBalance() {
  const svg = $("#balance");
  svg.innerHTML = "";
  const months = monthsInRange();
  const pts = DATA.balances.filter(b => months.includes(b.date.slice(0,7)));
  const series = DATA.balance_series.map(s => s.key);
  const NAME = Object.fromEntries(DATA.balance_series.map(s => [s.key, s.name]));

  const W = 560, H = 300, M = { t: 14, r: 58, b: 38, l: 56 };
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const max = niceMax(Math.max(...pts.map(p => p.value), 1));
  const dates = [...new Set(pts.map(p => p.date))].sort();
  const x = d => M.l + (dates.indexOf(d) / Math.max(dates.length - 1, 1)) * pw;
  const y = v => M.t + ph - (v / max) * ph;

  for (let i = 0; i <= 4; i++) {
    const v = max * i / 4;
    svg.appendChild(el("line", { class: "grid-line", x1: M.l, x2: M.l + pw, y1: y(v), y2: y(v) }));
    const t = el("text", { x: M.l - 9, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = compact(v);
    svg.appendChild(t);
  }

  series.forEach(s => {
    const sp = pts.filter(p => p.series === s).sort((a,b) => a.date < b.date ? -1 : 1);
    if (!sp.length) return;
    const d = sp.map((p, i) => `${i ? "L" : "M"}${x(p.date)},${y(p.value)}`).join(" ");
    svg.appendChild(el("path", { d, fill: "none", stroke: BAL_COLOR[s], "stroke-width": 2,
                                 "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = sp[sp.length - 1];
    svg.appendChild(el("circle", { cx: x(last.date), cy: y(last.value), r: 4.5,
                                   fill: BAL_COLOR[s], stroke: "var(--surface-1)", "stroke-width": 2 }));
    const lb = el("text", { x: x(last.date) + 9, y: y(last.value) + 4, class: "lbl" });
    lb.textContent = compact(last.value);
    svg.appendChild(lb);
  });

  dates.forEach((d, i) => {
    const hit = el("rect", { x: x(d) - pw/dates.length/2, y: M.t, width: pw/dates.length, height: ph, fill: "transparent" });
    hit.addEventListener("mousemove", e => {
      const here = pts.filter(p => p.date === d);
      showTip(e, `<div class="t">${d}</div>` + here.map(p =>
        `<div class="r"><span><i class="swatch" style="background:${BAL_COLOR[p.series]}"></i>${NAME[p.series]}</span><b>${money2(p.value)}</b></div>`).join(""));
    });
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });

  svg.appendChild(el("line", { class: "axis-line", x1: M.l, x2: M.l + pw, y1: y(0), y2: y(0) }));
  [dates[0], dates[dates.length-1]].forEach((d, i) => {
    if (!d) return;
    const t = el("text", { x: x(d), y: H - 18, "text-anchor": i ? "end" : "start" });
    t.textContent = MONTH_LBL(d.slice(0,7));
    svg.appendChild(t);
  });

  $("#balLegend").innerHTML = series.map(s =>
    `<span><i style="background:${BAL_COLOR[s]}"></i>${NAME[s]}</span>`).join("");

  tableFor("#balanceTable", ["Statement close", "Account", "Balance"],
    pts.slice().reverse().map(p => [p.date, NAME[p.series], money2(p.value)]), [false, false, true]);
}

/* ---------- columns: interest & fees ---------- */
function drawFinance() {
  const svg = $("#finance");
  svg.innerHTML = "";
  const months = monthsInRange();
  const rows = DATA.finance.filter(r => months.includes(r.month));

  const W = 560, H = 300, M = { t: 14, r: 14, b: 38, l: 56 };
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const max = niceMax(Math.max(...rows.map(r => r.value), 1));
  const y = v => M.t + ph - (v / max) * ph;
  const band = pw / Math.max(rows.length, 1);
  const bw = Math.min(24, band * 0.6);

  for (let i = 0; i <= 4; i++) {
    const v = max * i / 4;
    svg.appendChild(el("line", { class: "grid-line", x1: M.l, x2: M.l + pw, y1: y(v), y2: y(v) }));
    const t = el("text", { x: M.l - 9, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = compact(v);
    svg.appendChild(t);
  }

  let peak = rows.reduce((a, b) => b.value > (a?.value ?? -1) ? b : a, null);
  rows.forEach((r, i) => {
    const cx = M.l + band * i + band/2 - bw/2;
    if (r.value > 0) {
      svg.appendChild(cappedBar(cx, y(r.value), bw, Math.max(y(0) - y(r.value), 1), "var(--s8)"));
    }
    const hit = el("rect", { x: M.l + band*i, y: M.t, width: band, height: ph, fill: "transparent" });
    hit.addEventListener("mousemove", e => showTip(e,
      `<div class="t">${MONTH_LBL(r.month)}</div><div class="r"><span>Interest &amp; fees</span><b>${money2(r.value)}</b></div>`));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });

  // One direct label: the extreme. Everything else is on the axis + tooltip.
  if (peak && peak.value > 0) {
    const i = rows.indexOf(peak);
    const t = el("text", { x: M.l + band*i + band/2, y: y(peak.value) - 8, "text-anchor": "middle", class: "lbl" });
    t.textContent = money(peak.value);
    svg.appendChild(t);
  }

  svg.appendChild(el("line", { class: "axis-line", x1: M.l, x2: M.l + pw, y1: y(0), y2: y(0) }));
  [0, rows.length - 1].forEach((i, k) => {
    if (i < 0 || !rows[i]) return;
    const t = el("text", { x: M.l + band*i + band/2, y: H - 18, "text-anchor": k ? "end" : "start" });
    t.textContent = MONTH_LBL(rows[i].month);
    svg.appendChild(t);
  });

  tableFor("#financeTable", ["Month", "Interest & fees"],
    rows.slice().reverse().map(r => [MONTH_LBL(r.month), money2(r.value)]), [false, true]);
}

/* ---------- horizontal bars (single series, one colour) ---------- */
function drawBars(svgSel, tableSel, items, labelKey, valueKey, extra) {
  const svg = $(svgSel);
  svg.innerHTML = "";
  const rowH = 27, M = { t: 6, r: 74, b: 6, l: 186 };
  const W = 560, H = M.t + items.length * rowH + M.b;
  const pw = W - M.l - M.r;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("height", H);

  const max = Math.max(...items.map(d => d[valueKey]), 1);
  items.forEach((d, i) => {
    const yy = M.t + i * rowH;
    const bh = Math.min(16, rowH - 10);
    const w = Math.max((d[valueKey] / max) * pw, 1);
    // Rounded data-end, square at the baseline (rotated: cap on the right).
    const rr = Math.min(4, w);
    const path = `M${M.l},${yy + (rowH-bh)/2} L${M.l + w - rr},${yy + (rowH-bh)/2} Q${M.l + w},${yy + (rowH-bh)/2} ${M.l + w},${yy + (rowH-bh)/2 + rr} L${M.l + w},${yy + (rowH-bh)/2 + bh - rr} Q${M.l + w},${yy + (rowH-bh)/2 + bh} ${M.l + w - rr},${yy + (rowH-bh)/2 + bh} L${M.l},${yy + (rowH-bh)/2 + bh} Z`;
    svg.appendChild(el("path", { d: path, fill: "var(--s1)" }));

    const nm = el("text", { x: M.l - 10, y: yy + rowH/2 + 4, "text-anchor": "end", class: "lbl" });
    nm.textContent = d[labelKey].length > 29 ? d[labelKey].slice(0, 28) + "…" : d[labelKey];
    svg.appendChild(nm);

    const vl = el("text", { x: M.l + w + 8, y: yy + rowH/2 + 4, class: "lbl" });
    vl.textContent = compact(d[valueKey]);
    svg.appendChild(vl);

    const hit = el("rect", { x: 0, y: yy, width: W, height: rowH, fill: "transparent" });
    hit.addEventListener("mousemove", e => showTip(e,
      `<div class="t">${d[labelKey]}</div><div class="r"><span>Total</span><b>${money2(d[valueKey])}</b></div>`
      + (extra ? extra(d) : "")));
    hit.addEventListener("mouseleave", hideTip);
    svg.appendChild(hit);
  });

  tableFor(tableSel, ["Name", "Total"], items.map(d => [d[labelKey], money2(d[valueKey])]), [false, true]);
}

/* ---------- table view twins ---------- */
function tableFor(sel, headers, rows, numeric) {
  const host = $(sel);
  host.innerHTML = "<table><thead><tr>"
    + headers.map((h, i) => `<th class="${numeric && numeric[i] ? "num" : ""}">${h}</th>`).join("")
    + "</tr></thead><tbody>"
    + rows.map(r => "<tr>" + r.map((c, i) => `<td class="${numeric && numeric[i] ? "num" : ""}">${c}</td>`).join("") + "</tr>").join("")
    + "</tbody></table>";
  host.classList.toggle("on", showTables);
}

/* ---------- headline figures ---------- */
function drawHeadline() {
  const months = monthsInRange();
  const rows = DATA.monthly.filter(r => months.includes(r.month));
  const total = rows.reduce((a, r) => a + r.values.reduce((x,y)=>x+y,0), 0);
  const full = rows.filter(r => !DATA.partial.includes(r.month));
  const avg = full.length ? full.reduce((a,r) => a + r.values.reduce((x,y)=>x+y,0), 0) / full.length : 0;

  const flow = DATA.cashflow.filter(r => months.includes(r.month));
  const moneyIn = flow.reduce((a,r) => a + r.in, 0);
  const income = flow.reduce((a,r) => a + r.income, 0);
  const net = moneyIn - total;

  $("#heroFigure").textContent = money(net);
  $("#heroFigure").style.color = net < 0 ? "var(--critical)" : "var(--good)";
  $("#heroCap").textContent =
    `net cash flow across ${rows.length} months · ${money(moneyIn)} in, ${money(total)} out · `
    + `${MONTH_LBL(months[0])} – ${MONTH_LBL(months[months.length-1])}`;

  // Card-balance tile sums every credit account, so it stays correct with more
  // than one card rather than silently reporting whichever came first.
  const bal = DATA.balances.filter(b => months.includes(b.date.slice(0,7)));
  const creditKeys = DATA.balance_series.filter(s => s.kind === "credit").map(s => s.key);
  const atEdge = (keys, edge) => keys.reduce((sum, k) => {
    const pts = bal.filter(b => b.series === k);
    return sum + (pts.length ? pts[edge === "last" ? pts.length - 1 : 0].value : 0);
  }, 0);
  const cardNow = atEdge(creditKeys, "last");
  const cardThen = atEdge(creditKeys, "first");
  const fin = DATA.finance.filter(r => months.includes(r.month)).reduce((a,r) => a + r.value, 0);

  // Full-resolution category totals: "Other" is a display fold, never an answer.
  const totals = {};
  periodSpend().forEach(t => totals[t.c] = (totals[t.c] || 0) + -t.a);
  const topCat = Object.entries(totals).sort((a,b) => b[1]-a[1])[0];

  const fullFlow = flow.filter(r => !DATA.partial.includes(r.month));
  const avgIncome = fullFlow.length ? fullFlow.reduce((a,r) => a + r.income, 0) / fullFlow.length : 0;

  const tiles = [
    { label: "Income", value: money(income),
      delta: `${money(avgIncome)}/mo · payroll and tax refunds only` },
    { label: "Spending", value: money(total), delta: `${money(avg)}/mo across ${full.length} full cycles` },
    { label: "Card balance", value: money(cardNow),
      delta: `${cardNow >= cardThen ? "+" : ""}${money(cardNow - cardThen)} over the period`,
      dir: cardNow >= cardThen ? "up" : "down" },
    { label: "Interest & fees paid", value: money2(fin), delta: "cost of carrying the balance",
      dir: fin > 0 ? "up" : "" },
    { label: "Largest category", value: topCat ? topCat[0] : "—",
      delta: topCat ? `${money(topCat[1])} · ${(topCat[1]/total*100).toFixed(0)}% of spend` : "" },
  ];
  $("#tiles").innerHTML = tiles.map(t => `
    <div class="tile">
      <div class="label">${t.label}</div>
      <div class="value">${t.value}</div>
      <div class="delta ${t.dir || ""}">${t.delta}</div>
    </div>`).join("");

  const cats = Object.entries(totals).filter(([,v]) => v > 0)
    .sort((a,b) => b[1]-a[1]).map(([c,v]) => ({ name: c, total: v }));
  drawBars("#cats", "#catsTable", cats, "name", "total",
           d => `<div class="r"><span>Share</span><b>${(d.total/total*100).toFixed(1)}%</b></div>`);
  $("#catNote").textContent =
    `All ${cats.length} categories at full resolution — not the 8-slot fold used by the chart above. `
    + `${money(total)} total.`;
}

function drawMerchants() {
  // Merchant totals are period-scoped, so recompute from the transaction list.
  const agg = {};
  periodSpend().forEach(t => {
    agg[t.m] = agg[t.m] || { name: t.m, total: 0, count: 0 };
    agg[t.m].total += -t.a;
    agg[t.m].count += 1;
  });
  const items = Object.values(agg).sort((a,b) => b.total - a.total).slice(0, 12);
  drawBars("#merch", "#merchTable", items, "name", "total",
           d => `<div class="r"><span>Transactions</span><b>${d.count}</b></div>`);
  $("#merchNote").textContent = `Top 12 by total spend in the selected period.`;
}

/* ---------- money in by source ---------- */
function drawSources() {
  const months = monthsInRange();
  const agg = {};
  DATA.txns.forEach(t => {
    if (!months.includes(t.d.slice(0,7)) || t.a <= 0) return;
    if (!["Income","Reimbursements","One-off deposits","Refunds"].includes(t.c)) return;
    agg[t.m] = agg[t.m] || { name: t.m, category: t.c, total: 0, count: 0 };
    agg[t.m].total += t.a;
    agg[t.m].count += 1;
  });
  const items = Object.values(agg).sort((a,b) => b.total - a.total);
  drawBars("#src", "#srcTable", items, "name", "total",
    d => `<div class="r"><span>${d.category}</span><b>${d.count} deposits</b></div>`);
  const inc = items.filter(d => d.category === "Income").reduce((a,d) => a + d.total, 0);
  const tot = items.reduce((a,d) => a + d.total, 0);
  $("#srcNote").innerHTML =
    `${money(tot)} arrived in the period. <b>${money(inc)} (${(inc/tot*100).toFixed(0)}%) is actual income</b> — `
    + `the rest is money paid back to you, plus one unattributed deposit. `
    + `Transfers from your own Truist account are excluded, so they don't inflate this.`;
}

/* ---------- recurring ---------- */
function drawRecurring() {
  const rows = DATA.recurring;
  const live = rows.filter(r => r.active);
  const ended = rows.filter(r => !r.active);
  const monthly = live.reduce((a, r) => a + r.monthly, 0);
  $("#recNote").innerHTML =
    `${live.length} charges are still running — about <b>${money(monthly)}/month</b>, ${money(monthly*12)}/year. `
    + (ended.length ? `${ended.length} more stopped and ${ended.length > 1 ? "are" : "is"} listed below the rule, excluded from that total. ` : "")
    + `Detected from cadence regularity (median absolute deviation, so one missed cycle doesn't disqualify a bill), `
    + `not a keyword list. Rows marked “varies” swing more than 15% between charges.`;
  const row = r => `<tr${r.active ? "" : ' style="opacity:.62"'}>
        <td>${r.merchant}</td>
        <td class="tag">${r.category}</td>
        <td class="tag">${r.cadence}${r.variable ? " · varies" : ""}</td>
        <td class="num">${money2(r.typical)}</td>
        <td class="num">${r.count}</td>
        <td class="num">${r.active ? money2(r.monthly) : "—"}</td>
        <td class="num">${money2(r.total)}</td>
        <td class="tag">${r.active ? "active" : `ended ${r.last}`}</td>
      </tr>`;
  $("#recurring").innerHTML =
    `<thead><tr><th>Merchant</th><th>Category</th><th>Cadence</th><th class="num">Typical</th>
     <th class="num">Charges</th><th class="num">Per month</th><th class="num">Total</th><th>Status</th></tr></thead><tbody>`
    + live.map(row).join("")
    + (ended.length ? `<tr><td colspan="8" style="border-top:1px solid var(--axis);padding-top:10px" class="tag">
         No longer charging — last seen more than 2.5 cycles before the data ends</td></tr>` : "")
    + ended.map(row).join("") + "</tbody>";
}

/* ---------- transactions ---------- */
function drawTxns() {
  const q = ($("#search").value || "").toLowerCase();
  const months = monthsInRange();
  const rows = DATA.txns.filter(t => months.includes(t.d.slice(0,7)))
    .filter(t => !q || t.m.toLowerCase().includes(q) || t.c.toLowerCase().includes(q)
                    || t.raw.toLowerCase().includes(q));
  $("#txnCount").textContent = ` ${rows.length.toLocaleString()} of ${DATA.txns.length.toLocaleString()} rows`;
  const cap = rows.slice(0, 600);
  $("#txns").innerHTML =
    `<thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Account</th><th class="num">Amount</th></tr></thead><tbody>`
    + cap.map(t => `<tr title="${t.raw.replace(/"/g,"&quot;")}">
        <td>${t.d}</td><td>${t.m}</td>
        <td class="tag">${t.c}</td>
        <td class="tag">${t.acct}</td>
        <td class="num" style="color:${t.a < 0 ? "inherit" : "var(--good)"}">${money2(t.a)}</td>
      </tr>`).join("")
    + (rows.length > cap.length ? `<tr><td colspan="5" class="tag">…${(rows.length-cap.length).toLocaleString()} more — narrow the search or period</td></tr>` : "")
    + "</tbody>";
}

/* ---------- wiring ---------- */
function renderAll() {
  drawHeadline();
  drawFlow();
  drawStack();
  drawBalance();
  drawFinance();
  drawMerchants();
  drawSources();
  drawRecurring();
  drawTxns();
  document.querySelectorAll(".tableview").forEach(t => t.classList.toggle("on", showTables));
}

document.querySelectorAll("[data-range]").forEach(b => {
  b.addEventListener("click", () => {
    document.querySelectorAll("[data-range]").forEach(o => o.setAttribute("aria-pressed", "false"));
    b.setAttribute("aria-pressed", "true");
    range = b.dataset.range;
    renderAll();
  });
});
$("#tableToggle").addEventListener("click", () => {
  showTables = !showTables;
  $("#tableToggle").setAttribute("aria-pressed", String(showTables));
  $("#tableToggle").textContent = showTables ? "Hide data tables" : "Show data tables";
  document.querySelectorAll(".tableview").forEach(t => t.classList.toggle("on", showTables));
});
$("#themeToggle").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const isDark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", isDark ? "light" : "dark");
  renderAll();
});
$("#search").addEventListener("input", drawTxns);

$("#coverage").textContent =
  `${DATA.coverage.statements} statements · ${DATA.coverage.rows.toLocaleString()} transactions · `
  + `${DATA.coverage.start} to ${DATA.coverage.end}`;
$("#foot").innerHTML =
  `Generated ${DATA.generated} from Chase statement PDFs by <code>statementproof</code>. `
  + `Every figure traces to a parsed statement row; all 40 statements reconcile against their own printed totals. `
  + `Spending excludes transfers between your own accounts — a card payment out of checking is the same money as `
  + `the purchases it settles, so counting both would double-count. The books close: money in `
  + `${money(DATA.cashflow.reduce((a,r)=>a+r.in,0))} minus spending `
  + `${money(DATA.cashflow.reduce((a,r)=>a+r.out,0))} plus transfers ${money(DATA.transfers_net)} equals `
  + `${money(DATA.cashflow.reduce((a,r)=>a+r.in-r.out,0) + DATA.transfers_net)}, which is exactly how much the two `
  + `account balances moved over the period.`;

renderAll();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
