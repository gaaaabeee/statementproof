"""The app's single page.

Kept as one self-contained string for the same reason the dashboard is: no
external assets, nothing to fetch, and the whole UI is auditable in one file.
Colours are the same validated palette the dashboard uses.
"""

from __future__ import annotations

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>statementproof</title>
<style>
  :root {
    color-scheme: light;
    --surface-1:#fcfcfb; --plane:#f9f9f7; --text-primary:#0b0b0b;
    --text-secondary:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
    --border:rgba(11,11,11,0.10); --good:#006300; --critical:#d03b3b;
    --accent:#2a78d6; --warn:#eb6834;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --surface-1:#1a1a19; --plane:#0d0d0d; --text-primary:#fff;
      --text-secondary:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835;
      --border:rgba(255,255,255,0.10); --good:#0ca30c; --critical:#d03b3b;
      --accent:#3987e5; --warn:#d95926;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--text-primary);
       font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1000px;margin:0 auto;padding:28px 20px 80px}
  header{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px}
  h1{font-size:19px;font-weight:600;margin:0;letter-spacing:-.01em}
  .sub{color:var(--text-secondary);font-size:13px}
  .card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;
        padding:18px 20px;margin-bottom:16px}
  .card h2{font-size:14px;font-weight:600;margin:0 0 2px;
           display:flex;align-items:center;gap:9px}
  .step{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
        border-radius:50%;background:var(--text-primary);color:var(--surface-1);
        font-size:11px;font-weight:600;flex:none}
  .card p.note{font-size:13px;color:var(--text-secondary);margin:2px 0 14px}
  button{font:inherit;font-size:13px;color:var(--text-secondary);background:var(--surface-1);
         border:1px solid var(--border);border-radius:8px;padding:7px 13px;cursor:pointer}
  button:hover:not(:disabled){color:var(--text-primary)}
  button:disabled{opacity:.45;cursor:not-allowed}
  button.primary{background:var(--accent);color:#fff;border-color:transparent;font-weight:500}
  button.primary:hover:not(:disabled){filter:brightness(1.08);color:#fff}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  #drop{border:1.5px dashed var(--axis);border-radius:10px;padding:26px;text-align:center;
        color:var(--text-secondary);font-size:13px;transition:.12s;cursor:default}
  #drop.hot{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 7%,transparent);
            color:var(--text-primary)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;font-weight:600;color:var(--text-secondary);padding:6px 9px;
     border-bottom:1px solid var(--border)}
  td{padding:6px 9px;border-bottom:1px solid var(--grid);vertical-align:middle}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .tag{font-size:12px;color:var(--text-secondary)}
  .ok{color:var(--good)} .bad{color:var(--critical)} .warn{color:var(--warn)}
  .pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;
        border:1px solid var(--border);color:var(--text-secondary)}
  .scroll{max-height:340px;overflow:auto}
  select,input[type=text]{font:inherit;font-size:13px;padding:5px 8px;border-radius:7px;
        border:1px solid var(--border);background:var(--plane);color:var(--text-primary)}
  .muted{color:var(--muted)}
  label.achbox{white-space:nowrap;display:inline-flex;align-items:center;gap:4px;margin-left:6px}
  .hidden{display:none}
  .foot{color:var(--muted);font-size:12.5px;margin-top:22px;line-height:1.6}
  .banner{border-radius:9px;padding:10px 13px;font-size:13px;margin-bottom:12px}
  .banner.bad{background:color-mix(in srgb,var(--critical) 12%,transparent);color:var(--critical)}
  .banner.ok{background:color-mix(in srgb,var(--good) 12%,transparent);color:var(--good)}
  .guess{color:var(--warn);white-space:nowrap}
  code{font-size:12px;background:var(--plane);padding:1px 5px;border-radius:4px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>statementproof</h1>
    <span class="sub" id="where"></span>
  </header>
  <p class="sub" style="margin:0 0 20px">
    Everything below runs on this machine. The page is served from
    <code>127.0.0.1</code> and nothing is ever sent anywhere.
  </p>

  <div class="card">
    <h2><span class="step">1</span> Statements</h2>
    <p class="note">Drop PDFs here, or choose a folder you already keep them in.
       Files are identified by reading them, never by their name.</p>
    <div id="drop">Drop statement PDFs here</div>
    <div class="row" style="margin-top:12px">
      <button id="pick">Choose folder…</button>
      <button id="useLibrary">Use my library</button>
      <span class="tag" id="srcInfo"></span>
    </div>
    <div id="detected" style="margin-top:14px"></div>
  </div>

  <div class="card">
    <h2><span class="step">2</span> Verify</h2>
    <p class="note">Every figure is checked against totals the statement prints itself.
       If a check fails, nothing gets generated.</p>
    <div class="row"><button id="verify" class="primary">Verify statements</button>
      <span class="tag" id="verifyInfo"></span></div>
    <div id="verifyOut" style="margin-top:14px"></div>
  </div>

  <div class="card">
    <h2><span class="step">3</span> Label what's left</h2>
    <p class="note">Merchants no shipped rule recognizes — usually local ones.
       Labelling saves a rule to your own config and applies immediately.</p>
    <div id="labelOut"><span class="tag muted">Verify first.</span></div>
  </div>

  <div class="card">
    <h2><span class="step">4</span> Generate</h2>
    <p class="note">Writes the CSVs and the dashboard into your library.</p>
    <div class="row">
      <button id="generate" class="primary" disabled>Generate dashboard</button>
      <button id="open" class="hidden">Open dashboard</button>
      <span class="tag" id="genInfo"></span>
    </div>
  </div>

  <p class="foot" id="foot"></p>
</div>

<script>
const T = "__TOKEN__";
const $ = s => document.querySelector(s);
const money = n => (n<0?"-":"") + "$" + Math.abs(n).toLocaleString(undefined,{maximumFractionDigits:0});

async function api(path, opts = {}) {
  const url = path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(T);
  const r = await fetch(url, { headers: { "X-Token": T, ...(opts.headers||{}) }, ...opts });
  if (!r.ok) return { ok:false, error: `${r.status} ${r.statusText}` };
  return r.json();
}

/* ---------- 1. source ---------- */
function renderDetected(d) {
  if (!d || d.cancelled) return;
  if (!d.ok) { $("#detected").innerHTML = `<div class="banner bad">${d.error}</div>`; return; }
  $("#srcInfo").textContent = d.folder;
  const counts = Object.entries(d.counts||{}).map(([k,v]) => `${v} × ${k}`).join(" · ");
  let html = d.files.length
    ? `<div class="banner ok">${d.files.length} statement${d.files.length===1?"":"s"} identified — ${counts}</div>`
    : `<div class="banner bad">No supported statements found in that folder.</div>`;
  if (d.skipped.length) {
    html += `<div class="banner bad">${d.skipped.length} file(s) not recognized:<br>`
          + d.skipped.map(s => `<span class="tag">${s.why}</span>`).join("<br>") + `</div>`;
  }
  $("#detected").innerHTML = html;
  $("#verify").disabled = d.files.length === 0;
}

const drop = $("#drop");
["dragenter","dragover"].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add("hot");
}));
["dragleave","drop"].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove("hot");
}));
drop.addEventListener("drop", async ev => {
  const files = [...ev.dataTransfer.files].filter(f => f.name.toLowerCase().endsWith(".pdf"));
  if (!files.length) { drop.textContent = "Those weren't PDFs."; return; }
  drop.textContent = `Importing ${files.length} file(s)…`;
  let ok = 0, bad = [];
  for (const f of files) {
    const buf = await f.arrayBuffer();
    const r = await api("/api/upload", { method:"POST", body: buf,
      headers: { "X-Filename": f.name, "Content-Type": "application/pdf" } });
    r.ok ? ok++ : bad.push(`${f.name}: ${r.error}`);
  }
  drop.textContent = `Imported ${ok} file(s)` + (bad.length ? ` · ${bad.length} rejected` : "");
  if (bad.length) $("#detected").innerHTML = `<div class="banner bad">${bad.join("<br>")}</div>`;
  renderDetected(await api("/api/use-folder", { method:"POST",
    body: JSON.stringify({ folder: LIBRARY_STATEMENTS }) }));
});

$("#pick").onclick = async () => renderDetected(await api("/api/pick-folder"));
$("#useLibrary").onclick = async () => renderDetected(await api("/api/use-folder",
  { method:"POST", body: JSON.stringify({ folder: LIBRARY_STATEMENTS }) }));

/* ---------- 2. verify ---------- */
$("#verify").onclick = async () => {
  $("#verifyInfo").textContent = "checking…";
  const v = await api("/api/verify");
  if (!v.ok) { $("#verifyOut").innerHTML = `<div class="banner bad">${v.error}</div>`;
               $("#verifyInfo").textContent = ""; return; }
  const t = v.totals;
  const clean = v.can_generate;
  let html = `<div class="banner ${clean?"ok":"bad"}">`
    + `${t.statements} statements · ${t.transactions.toLocaleString()} transactions · `
    + `${t.failed_checks} failed checks · ${t.unparsed} unparsed lines · `
    + `${t.continuity_problems} continuity problems`
    + (clean ? "" : "<br><b>Generation is blocked until these are resolved.</b>") + `</div>`;
  html += `<div class="row" style="margin-bottom:10px">` + v.accounts.map(a =>
    `<span class="pill">${a.label} · ${a.statements}</span>`).join(" ") + `</div>`;
  if (v.continuity.length)
    html += `<div class="banner bad">` + v.continuity.map(p=>`<div>${p}</div>`).join("") + `</div>`;
  html += `<div class="scroll"><table><thead><tr><th>Statement</th><th>Account</th>`
        + `<th>Period</th><th class="num">Rows</th><th>Checks</th></tr></thead><tbody>`
        + v.statements.map(s => `<tr><td>${s.file}</td><td class="tag">${s.account}</td>`
          + `<td class="tag">${s.period}</td><td class="num">${s.rows}</td>`
          + `<td class="${s.failed.length?"bad":"ok"}">`
          + (s.failed.length ? s.failed.map(f=>`${f.check} (Δ${f.delta})`).join(", ")
                             : `all ${s.checks} passed`) + `</td></tr>`).join("")
        + `</tbody></table></div>`;
  $("#verifyOut").innerHTML = html;
  $("#verifyInfo").textContent = "";
  $("#generate").disabled = !clean;
  loadLabels();
};

/* ---------- 3. labeling ---------- */
let CATEGORIES = [];
async function loadLabels() {
  const u = await api("/api/uncategorized");
  if (!u.ok) { $("#labelOut").innerHTML = `<span class="tag muted">${u.error}</span>`; return; }
  CATEGORIES = u.categories;
  if (!u.items.length) {
    $("#labelOut").innerHTML = `<div class="banner ok">Everything is categorized.</div>`; return;
  }
  const rows = u.items.map((it, i) => `
    <tr data-m="${encodeURIComponent(it.merchant)}" data-guess="${it.guess || ""}">
      <td>${it.merchant}<div class="tag muted">${it.sample}</div></td>
      <td class="num">${it.count}</td>
      <td class="num">${money(it.total)}</td>
      <td>
        <select data-role="cat">
          <option value="">— category —</option>
          ${CATEGORIES.map(c=>`<option>${c}</option>`).join("")}
        </select>
        ${it.guess ? `<span class="tag guess" data-role="guessflag" title="A loose keyword match, not a verified rule -- check it before saving">guess: ${it.guess}</span>` : ""}
        ${it.ach ? `<label class="tag achbox" title="Key the rule on the ACH originator id (${it.ach}), which does not change from month to month"><input type="checkbox" data-role="ach" checked>ACH&nbsp;id</label>` : ""}
      </td>
      <td><button data-role="save">Save</button> <span class="tag" data-role="msg"></span></td>
    </tr>`).join("");
  $("#labelOut").innerHTML =
    `<div class="banner bad">${money(u.remaining)} across ${u.items.length} merchants unlabeled</div>`
    + `<div class="row" style="margin-bottom:10px">`
    + `<button id="autoCat">Auto-categorize</button>`
    + `<button id="saveAll">Save all</button>`
    + `<span class="tag" id="bulkMsg"></span></div>`
    + `<div class="scroll"><table><thead><tr><th>Merchant</th><th class="num">Txns</th>`
    + `<th class="num">Total</th><th>Category</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;

  // Shared by the per-row Save button and Save all, so both go through the
  // same verified-before-write path -- a bulk action must not be a shortcut
  // around the check that a rule only matches the rows it claims to.
  async function saveRow(tr) {
    const merchant = decodeURIComponent(tr.dataset.m);
    const cat = tr.querySelector('[data-role="cat"]').value;
    const achBox = tr.querySelector('[data-role="ach"]');
    const msg = tr.querySelector('[data-role="msg"]');
    if (!cat) { msg.textContent = "pick a category"; return "skipped"; }
    msg.textContent = "saving…";
    const r = await api("/api/label", { method:"POST", body: JSON.stringify({
      merchant, category: cat, use_ach: achBox ? achBox.checked : false }) });
    if (!r.ok) { msg.innerHTML = `<span class="bad">${r.error}</span>`; return "failed"; }
    tr.style.opacity = .45;
    msg.innerHTML = `<span class="ok">saved</span>`;
    return "saved";
  }

  $("#labelOut").querySelectorAll('[data-role="save"]').forEach(btn => {
    btn.onclick = async () => {
      btn.disabled = true;
      const outcome = await saveRow(btn.closest("tr"));
      if (outcome !== "saved") { btn.disabled = false; return; }
      setTimeout(loadLabels, 400);
    };
  });

  // Fills every still-blank dropdown with its guess, if it has one. Never
  // overwrites a category the user already picked, and never saves anything
  // by itself -- the user reviews (or overrides) each guess, then saves.
  $("#autoCat").onclick = () => {
    const trs = [...$("#labelOut").querySelectorAll("tbody tr")];
    let filled = 0;
    trs.forEach(tr => {
      const guess = tr.dataset.guess;
      const select = tr.querySelector('[data-role="cat"]');
      if (guess && !select.value) { select.value = guess; filled++; }
    });
    const skipped = trs.length - filled;
    $("#bulkMsg").textContent = filled
      ? `filled ${filled} of ${trs.length} — review each, then Save all`
        + (skipped ? ` (${skipped} had no confident guess)` : "")
      : "no confident guesses for what's left — pick categories by hand";
  };

  $("#saveAll").onclick = async () => {
    $("#autoCat").disabled = true;
    const btn = $("#saveAll");
    btn.disabled = true;
    const trs = [...$("#labelOut").querySelectorAll("tbody tr")];
    let saved = 0, skipped = 0, failed = 0;
    for (const tr of trs) {
      const before = tr.querySelector('[data-role="cat"]').value;
      if (!before) { skipped++; continue; }
      const outcome = await saveRow(tr);
      if (outcome === "saved") saved++;
      else if (outcome === "failed") failed++;
      else skipped++;
    }
    $("#bulkMsg").innerHTML = `saved ${saved}`
      + (skipped ? `, ${skipped} skipped (no category chosen)` : "")
      + (failed ? `, <span class="bad">${failed} failed</span>` : "");
    if (saved) setTimeout(loadLabels, 600); else { btn.disabled = false; $("#autoCat").disabled = false; }
  };
}

/* ---------- 4. generate ---------- */
$("#generate").onclick = async () => {
  $("#genInfo").textContent = "generating…";
  const r = await api("/api/generate", { method:"POST", body:"{}" });
  if (!r.ok) { $("#genInfo").innerHTML = `<span class="bad">${r.error}</span>`; return; }
  $("#genInfo").innerHTML = `<span class="ok">${r.rows.toLocaleString()} transactions written</span>`;
  $("#open").classList.remove("hidden");
};
$("#open").onclick = () => window.open("/dashboard?t=" + encodeURIComponent(T), "_blank");

/* ---------- boot ---------- */
let LIBRARY_STATEMENTS = "";
(async () => {
  const s = await api("/api/state");
  LIBRARY_STATEMENTS = s.library + "/statements";
  $("#where").textContent = "library: " + s.library;
  $("#foot").innerHTML = `Rules are saved to <code>${s.rules}</code>. `
    + `That file names real people and payees — keep it off source control. `
    + `This app makes no network requests; the only socket is this loopback server.`;
  renderDetected(await api("/api/detect"));
  // #verify deep-link: open straight into a checked state, useful when the app
  // was launched pointing at a folder already.
  if (location.hash === "#verify" && !$("#verify").disabled) $("#verify").click();
})();
</script>
</body>
</html>
"""


def page(token: str) -> str:
    """The page, with this session's token baked in."""
    return TEMPLATE.replace("__TOKEN__", token)
