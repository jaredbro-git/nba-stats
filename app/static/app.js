// Shared page behaviour: schedule tabs, clickable rows, the "Out" checkboxes and their dock
// and the career chart on player pages.

// Tabs: buttons with data-tab="x" show #tab-x and hide its siblings.
document.querySelectorAll(".tabs").forEach((tabs) => {
  tabs.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-tab]");
    if (!button) return;
    tabs.querySelectorAll("button[data-tab]").forEach((b) => {
      const selected = b === button;
      b.setAttribute("aria-selected", String(selected));
      document.getElementById(`tab-${b.dataset.tab}`).hidden = !selected;
    });
  });
});

// Inside the game popup, game pages stay in the popup and everything else (teams, players) opens in the main window.
const embedded = document.documentElement.classList.contains("embedded");
function go(href) {
  (embedded && !href.startsWith("/game/") && !href.startsWith("?") ? window.top : window).location.href = href;
}
if (embedded) {
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented) return;
    const href = link.getAttribute("href");
    if (href.startsWith("/") && !href.startsWith("/game/")) { event.preventDefault(); window.top.location.href = href; }
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") window.parent.closeGamePopup?.(); });
}

// Table rows with data-href open that page when clicked anywhere (links inside still work).
document.querySelectorAll("tr[data-href]").forEach((row) => {
  row.addEventListener("click", (event) => {
    if (event.target.closest("a, button, input")) return;
    go(row.dataset.href);
  });
});

// Game cards (Today page) open the game in a popup instead of leaving the page. The popup is the real game
// page in an iframe, so its Out switches, dock and matchup pickers all work; if anything was saved or
// changed in it, the page behind reloads when it closes. Cmd/Ctrl-click still opens the full page.
function initGamePopups(selector) {
  const dialog = document.getElementById("game-popup");
  if (!dialog) return;
  const frame = dialog.querySelector("iframe");
  const full = dialog.querySelector("[data-full-page]");
  let loads = 0;
  frame.addEventListener("load", () => {
    loads += 1;
    try { full.href = frame.contentWindow.location.pathname + frame.contentWindow.location.search; } catch (e) { /* not same-origin */ }
  });
  window.closeGamePopup = () => dialog.close();
  dialog.addEventListener("close", () => {
    const changed = loads > 1;
    frame.src = "about:blank";
    loads = 0;
    if (changed) window.location.reload();
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });  // the backdrop
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  document.querySelectorAll(selector).forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      loads = 0;
      frame.src = card.getAttribute("href");
      full.href = card.getAttribute("href");
      dialog.showModal();
    });
  });
}

// "Out" checkboxes (game and team pages): tick as many as you like without the page reloading. A bar
// docked at the bottom of the window (#out-dock) then offers to update the prediction (?out=, when
// `preview`) or save them; its buttons submit #out-form, whose hidden "out" input follows the ticks.
// shown: who's out in what the page shows now; saved: the real list (game's own, or all-games).
function initOutDock(shown, saved, preview) {
  const boxes = [...document.querySelectorAll(".out-toggle")];
  const form = document.getElementById("out-form");
  const dock = document.getElementById("out-dock");
  if (!form || !dock || !boxes.length) return;
  const asSet = (ids) => new Set(ids.map(String));
  const showing = asSet(shown), real = asSet(saved);
  const ticked = () => new Set(boxes.filter((b) => b.checked).map((b) => b.value));
  const differ = (a, b) => [...a].filter((x) => !b.has(x)).length + [...b].filter((x) => !a.has(x)).length;
  const reset = () => boxes.forEach((b) => { b.checked = showing.has(b.value); });

  function update() {
    const now = ticked();
    form.elements.out.value = [...now].join(",");
    boxes.forEach((b) => b.closest("tr")?.classList.toggle("is-out", b.checked));
    const pending = differ(now, showing), unsaved = differ(now, real);
    dock.hidden = !pending && !unsaved;
    dock.querySelector("[data-preview]")?.toggleAttribute("hidden", !preview || !pending);
    dock.querySelector("[data-undo]").hidden = !pending;
    dock.querySelectorAll("[data-save]").forEach((b) => { b.disabled = !unsaved; });
    dock.querySelector("[data-dock-text]").textContent = pending
      ? `${pending} change${pending === 1 ? "" : "s"}${preview ? " not in the prediction yet" : " not saved yet"}`
      : "Previewing: not saved";
  }

  reset();
  boxes.forEach((b) => b.addEventListener("change", update));
  dock.querySelector("[data-preview]")?.addEventListener("click", () => {
    const params = new URLSearchParams(window.location.search);
    params.set("out", form.elements.out.value);
    window.location.search = params.toString();
  });
  dock.querySelector("[data-undo]").addEventListener("click", () => { reset(); update(); });
  update();
}

// Player page: points, rebounds and assists per game for each season. A season split
// between teams uses its combined ("TOT") row.
function drawCareer(seasons, teams, pts, reb, ast) {
  const rows = new Map();
  seasons.forEach((season, i) => {
    if (!rows.has(season) || teams[i] === "TOT") rows.set(season, { pts: pts[i], reb: reb[i], ast: ast[i] });
  });
  const labels = [...rows.keys()];
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const series = [
    ["Points", "pts", "--series-1"],
    ["Rebounds", "reb", "--series-2"],
    ["Assists", "ast", "--series-3"],
  ];
  new Chart(document.getElementById("career-chart"), {
    type: "line",
    data: {
      labels,
      datasets: series.map(([label, key, token]) => ({
        label,
        data: labels.map((s) => rows.get(s)[key]),
        borderColor: color(token),
        backgroundColor: color(token),
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        tension: 0.25,
      })),
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: color("--text-2"), maxRotation: 0, autoSkipPadding: 12 }, border: { color: color("--axis") } },
        y: { beginAtZero: true, grid: { color: color("--grid") }, ticks: { color: color("--text-2") }, border: { display: false },
             title: { display: true, text: "Per game", color: color("--text-2") } },
      },
    },
  });
}

// Game page: picking a different defender reloads with ?mu=shooter:defender for every changed matchup.
function initMatchupSelects() {
  const selects = document.querySelectorAll(".matchup-select");
  selects.forEach((select) => {
    select.addEventListener("change", () => {
      const changed = [...selects]
        .filter((s) => s.value !== s.dataset.likely)
        .map((s) => `${s.dataset.shooter}:${s.value}`);
      const params = new URLSearchParams(window.location.search);
      if (changed.length) params.set("mu", changed.join(",")); else params.delete("mu");
      selects.forEach((s) => { s.disabled = true; });
      window.location.search = params.toString();
    });
  });
}

// Filter forms marked data-autosubmit submit as soon as a select changes.
document.querySelectorAll("form[data-autosubmit] select").forEach((select) => {
  select.addEventListener("change", () => select.form.submit());
});

// Shot charts: a tooltip for the hexagon under the pointer (or focused with the keyboard).
document.querySelectorAll(".shot-figure").forEach((figure) => {
  const tip = figure.querySelector(".shot-tip");
  const show = (hex, x, y) => {
    const [zone, made, league, diff] = hex.dataset.tip.split("|");
    tip.innerHTML = `<b>${zone}</b><span>${made}</span><span>${league} · ${diff}</span>`;
    tip.hidden = false;
    const box = figure.getBoundingClientRect();
    const left = Math.min(Math.max(x - box.left + 12, 4), box.width - tip.offsetWidth - 4);
    const top = y - box.top - tip.offsetHeight - 12;
    tip.style.left = `${left}px`;
    tip.style.top = `${top < 0 ? y - box.top + 18 : top}px`;
  };
  figure.addEventListener("pointermove", (event) => {
    const hex = event.target.closest(".hex");
    if (hex) show(hex, event.clientX, event.clientY); else tip.hidden = true;
  });
  figure.addEventListener("pointerleave", () => { tip.hidden = true; });
  figure.addEventListener("focusin", (event) => {
    const hex = event.target.closest(".hex");
    if (!hex) return;
    const r = hex.getBoundingClientRect();
    show(hex, r.left + r.width / 2, r.top);
  });
  figure.addEventListener("focusout", () => { tip.hidden = true; });
});

// Matchup popup: a row or button with data-matchup / data-matchup-open="shooter:defender" loads the
// expected outcome of that matchup into the page's <dialog id="matchup-dialog">.
(() => {
  const dialog = document.getElementById("matchup-dialog");
  if (!dialog) return;
  async function open(pair) {
    const [shooter, defender] = pair.split(":");
    dialog.innerHTML = '<p class="muted">Loading…</p>';
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(`/matchup-detail?shooter=${shooter}&defender=${defender}`);
      if (!response.ok) throw new Error(response.statusText);
      dialog.innerHTML = await response.text();
    } catch {
      dialog.innerHTML = '<p class="bad">Couldn\'t load this matchup.</p><button type="button" class="secondary small" data-dialog-close>Close</button>';
    }
  }
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-dialog-close]")) { dialog.close(); return; }
    const button = event.target.closest("[data-matchup-open]");
    if (button) { open(button.dataset.matchupOpen); return; }
    const row = event.target.closest("tr[data-matchup]");
    if (row && !event.target.closest("a, select, input")) open(row.dataset.matchup);
  });
  // Clicking the dimmed backdrop closes it.
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  window.openMatchup = open;
})();

// Player search boxes for matchups. A box with data-fixed-shooter / data-fixed-defender opens the
// popup as soon as a player is picked; boxes inside .pair-search fill a shooter or defender slot.
document.querySelectorAll(".player-search").forEach((box) => {
  const input = box.querySelector("input");
  const list = box.querySelector(".ps-results");
  let results = [];
  let active = -1;
  let timer;

  function render() {
    list.innerHTML = "";
    results.forEach((p, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      li.innerHTML = `<span>${p.name}</span><small>${p.team || (p.tracked ? "" : "no tracked matchups")}</small>`;
      li.addEventListener("mousedown", (event) => { event.preventDefault(); pick(p); });
      list.appendChild(li);
    });
    list.hidden = results.length === 0;
    input.setAttribute("aria-expanded", String(!list.hidden));
  }

  function pick(p) {
    results = []; active = -1; render();
    if (box.closest(".scenario-add") && window.onPlayerPicked) { input.value = ""; window.onPlayerPicked(p); return; }
    if (box.dataset.slot === "go") { window.location.href = `/players/${p.id}`; return; }
    // Pages that handle picks themselves (comparisons) define window.onSlotPicked(slot, player).
    if (box.dataset.slot && window.onSlotPicked) { input.value = p.name; window.onSlotPicked(box.dataset.slot, p); return; }
    if (box.dataset.fixedShooter) { input.value = ""; window.openMatchup(`${box.dataset.fixedShooter}:${p.id}`); return; }
    if (box.dataset.fixedDefender) { input.value = ""; window.openMatchup(`${p.id}:${box.dataset.fixedDefender}`); return; }
    input.value = p.name;
    box.dataset.picked = p.id;
    const pair = box.closest(".pair-search");
    if (pair) {
      const go = pair.querySelector(".pair-go");
      const shooter = pair.querySelector('[data-slot="shooter"]').dataset.picked;
      const defender = pair.querySelector('[data-slot="defender"]').dataset.picked;
      go.disabled = !(shooter && defender);
    }
  }

  input.addEventListener("input", () => {
    delete box.dataset.picked;
    const go = box.closest(".pair-search")?.querySelector(".pair-go");
    if (go) go.disabled = true;
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { results = []; render(); return; }
    timer = setTimeout(async () => {
      try {
        const response = await fetch(`/player-search?q=${encodeURIComponent(q)}`);
        results = await response.json();
        active = results.length ? 0 : -1;
        render();
      } catch { results = []; render(); }
    }, 150);
  });
  input.addEventListener("keydown", (event) => {
    if (list.hidden) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      render();
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      pick(results[active]);
    } else if (event.key === "Escape") {
      results = []; render();
    }
  });
  input.addEventListener("blur", () => setTimeout(() => { results = []; render(); }, 150));
});

document.querySelectorAll(".pair-search .pair-go").forEach((go) => {
  go.addEventListener("click", () => {
    const pair = go.closest(".pair-search");
    const shooter = pair.querySelector('[data-slot="shooter"]').dataset.picked;
    const defender = pair.querySelector('[data-slot="defender"]').dataset.picked;
    if (shooter && defender) window.openMatchup(`${shooter}:${defender}`);
  });
});

// Sortable, filterable tables. Rows carry their values in data-* attributes; empty values always sort
// last. Controls in .mu-controls[data-for=<table id>] filter rows: data-filter="key" (equal),
// data-filter-min="key" (at least), data-filter-text="key" (contains, several words all must match),
// data-hide-never (rows with data-never="1"). One controls block can serve several tables
// (data-for="a b"), and a table can have several. Shows `data-page` rows at a time, then "Show more".
// Ties break on data-tiebreak.
document.querySelectorAll("table[data-sortable]").forEach((table) => {
  const tbody = table.tBodies[0];
  const rows = [...tbody.rows];
  const controlSets = [...document.querySelectorAll(`.mu-controls[data-for~="${table.id}"]`)];
  const controls = controlSets.find((c) => c.dataset.for === table.id) || controlSets[0];
  const all = (selector) => controlSets.flatMap((c) => [...c.querySelectorAll(selector)]);
  const more = document.querySelector(`.mu-more[data-more-for="${table.id}"]`);
  const pageSize = Number(table.dataset.page) || 25;
  const tiebreak = table.dataset.tiebreak || "poss";
  const preset = controls?.querySelector("[data-sort-preset]");
  let [sortKey, sortDir] = (preset?.value || table.dataset.sort || "poss:desc").split(":");
  let shown = pageSize;

  const value = (row, key) => {
    const v = row.dataset[key];
    if (v === "" || v === undefined) return null;
    const n = Number(v);
    return Number.isNaN(n) ? v.toLowerCase() : n;
  };
  const tie = (a, b) => (Number(b.dataset[tiebreak]) || 0) - (Number(a.dataset[tiebreak]) || 0);

  function keep(row) {
    if (!controls) return true;
    for (const el of all("[data-filter]")) {
      if (el.value && row.dataset[el.dataset.filter] !== el.value) return false;
    }
    for (const el of all("[data-filter-min]")) {
      const min = Number(el.value || 0);
      if (min && !(row.dataset.never === "1") && !((Number(row.dataset[el.dataset.filterMin]) || 0) >= min)) return false;
    }
    for (const el of all("[data-filter-text]")) {
      const text = (row.dataset[el.dataset.filterText] || "").toLowerCase();
      if (el.value.trim().toLowerCase().split(/\s+/).some((word) => word && !text.includes(word))) return false;
    }
    if (all("[data-hide-never]").some((el) => el.checked) && row.dataset.never === "1") return false;
    return true;
  }

  function apply() {
    const kept = rows.filter(keep);
    const dir = sortDir === "asc" ? 1 : -1;
    kept.sort((a, b) => {
      const va = value(a, sortKey), vb = value(b, sortKey);
      if (va === null && vb === null) return tie(a, b);
      if (va === null) return 1;
      if (vb === null) return -1;
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return tie(a, b);
    });
    rows.forEach((r) => { r.hidden = true; });
    kept.forEach((r, i) => { r.hidden = i >= shown; tbody.appendChild(r); });
    table.querySelectorAll("th button[data-sort]").forEach((b) => {
      const th = b.closest("th");
      if (b.dataset.sort === sortKey) th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
    const count = document.querySelector(`.mu-count[data-count-for="${table.id}"]`) || controls?.querySelector(".mu-count");
    if (count) count.textContent = kept.length ? `Showing ${Math.min(shown, kept.length)} of ${kept.length}` : "Nothing matches";
    if (more) more.hidden = kept.length <= shown;
    if (preset && [...preset.options].some((o) => o.value === `${sortKey}:${sortDir}`)) preset.value = `${sortKey}:${sortDir}`;
  }

  table.querySelectorAll("th button[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      // First click: text A-Z, numbers high to low (or low to high for data-sort-asc columns); again flips it.
      const firstDir = button.hasAttribute("data-sort-asc") || ["name", "team"].includes(key) ? "asc" : "desc";
      sortDir = key === sortKey ? (sortDir === "asc" ? "desc" : "asc") : firstDir;
      sortKey = key;
      shown = pageSize;
      apply();
    });
  });
  preset?.addEventListener("change", () => { [sortKey, sortDir] = preset.value.split(":"); shown = pageSize; apply(); });
  all("select:not([data-sort-preset]), input").forEach((el) =>
    el.addEventListener("input", () => { shown = pageSize; apply(); }));
  more?.addEventListener("click", () => { shown += pageSize; apply(); });
  apply();
});

// Season simulator: the what-ifs live in ?miss=player:games,... (games = a number or "rest").
function initScenario() {
  const form = document.getElementById("scenario-form");
  const missInput = form.querySelector('input[name="miss"]');
  const current = () => new Map(missInput.value.split(",").filter(Boolean).map((p) => p.split(":")));
  const submit = (map) => {
    missInput.value = [...map].map(([id, games]) => `${id}:${games}`).join(",");
    form.submit();
  };
  window.onPlayerPicked = (p) => { const map = current(); map.set(String(p.id), map.get(String(p.id)) || "10"); submit(map); };
  form.querySelector('select[name="saved"]').addEventListener("change", () => form.submit());
  document.querySelectorAll(".scenario-games").forEach((select) => {
    select.addEventListener("change", () => { const map = current(); map.set(select.dataset.player, select.value); submit(map); });
  });
  document.querySelectorAll("[data-scenario-remove]").forEach((button) => {
    button.addEventListener("click", () => { const map = current(); map.delete(button.dataset.scenarioRemove); submit(map); });
  });
}

// Compare page: points per game by age for two players. careers: [[age, season, pts], ...]
function drawCareerCompare(a, b, nameA, nameB) {
  const css = getComputedStyle(document.documentElement);
  const color = (name) => css.getPropertyValue(name).trim();
  const points = (career) => career.filter((r) => r[0] !== null).map((r) => ({ x: Number(r[0]), y: r[2], season: r[1] }));
  new Chart(document.getElementById("career-compare"), {
    type: "line",
    data: {
      datasets: [
        { label: nameA, data: points(a), borderColor: color("--series-1"), backgroundColor: color("--series-1"), borderWidth: 2, pointRadius: 3, tension: 0.25 },
        { label: nameB, data: points(b), borderColor: color("--series-2"), backgroundColor: color("--series-2"), borderWidth: 2, pointRadius: 3, tension: 0.25 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} pts at ${ctx.parsed.x} (${ctx.raw.season})` } },
      },
      scales: {
        x: { type: "linear", title: { display: true, text: "Age", color: color("--text-2") }, grid: { display: false },
             ticks: { color: color("--text-2"), stepSize: 1 }, border: { color: color("--axis") } },
        y: { beginAtZero: true, title: { display: true, text: "Points per game", color: color("--text-2") },
             grid: { color: color("--grid") }, ticks: { color: color("--text-2") }, border: { display: false } },
      },
    },
  });
}
