// Shared page behaviour: schedule tabs, clickable rows, the game page's "Out" checkboxes
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

// Table rows with data-href open that page when clicked anywhere (links inside still work).
document.querySelectorAll("tr[data-href]").forEach((row) => {
  row.addEventListener("click", (event) => {
    if (event.target.closest("a, button, input")) return;
    window.location.href = row.dataset.href;
  });
});

// Game page: ticking "Out" reloads the page with ?out= listing every ticked player.
function initOutToggles(out) {
  const boxes = document.querySelectorAll(".out-toggle");
  const ids = new Set(out.map(String));
  boxes.forEach((box) => {
    box.checked = ids.has(box.value);
    box.addEventListener("change", () => {
      const ticked = [...boxes].filter((b) => b.checked).map((b) => b.value);
      const params = new URLSearchParams(window.location.search);
      params.set("out", ticked.join(","));
      boxes.forEach((b) => { b.disabled = true; });
      window.location.search = params.toString();
    });
  });
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

// Sortable, filterable matchup tables. Rows carry their values in data-* attributes; empty values
// (e.g. FG% for a pair that never met) always sort last. Shows `data-page` rows, then "Show more".
document.querySelectorAll("table[data-sortable]").forEach((table) => {
  const tbody = table.tBodies[0];
  const rows = [...tbody.rows];
  const controls = document.querySelector(`.mu-controls[data-for="${table.id}"]`);
  const more = document.querySelector(`.mu-more[data-more-for="${table.id}"]`);
  const pageSize = Number(table.dataset.page) || 25;
  const preset = controls?.querySelector("[data-sort-preset]");
  let [sortKey, sortDir] = (preset?.value || "poss:desc").split(":");
  let shown = pageSize;

  const value = (row, key) => {
    const v = row.dataset[key];
    if (key === "name") return v.toLowerCase();
    return v === "" || v === undefined ? null : Number(v);
  };

  function apply() {
    const minPoss = Number(controls?.querySelector("[data-min-poss]")?.value || 0);
    const group = controls?.querySelector("[data-group]")?.value || "";
    const name = (controls?.querySelector("[data-name-filter]")?.value || "").trim().toLowerCase();
    const hideNever = controls?.querySelector("[data-hide-never]")?.checked;
    const keep = rows.filter((r) =>
      (r.dataset.never === "1" ? !hideNever : Number(r.dataset.poss) >= minPoss) &&
      (!group || r.dataset.group === group) &&
      (!name || r.dataset.name.toLowerCase().includes(name)));
    const dir = sortDir === "asc" ? 1 : -1;
    keep.sort((a, b) => {
      const va = value(a, sortKey), vb = value(b, sortKey);
      if (va === null && vb === null) return Number(b.dataset.poss) - Number(a.dataset.poss);
      if (va === null) return 1;
      if (vb === null) return -1;
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return Number(b.dataset.poss) - Number(a.dataset.poss);
    });
    rows.forEach((r) => { r.hidden = true; });
    keep.forEach((r, i) => { r.hidden = i >= shown; tbody.appendChild(r); });
    table.querySelectorAll("th button[data-sort]").forEach((b) => {
      const th = b.closest("th");
      if (b.dataset.sort === sortKey) th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
    const count = controls?.querySelector(".mu-count");
    if (count) count.textContent = `Showing ${Math.min(shown, keep.length)} of ${keep.length}`;
    if (more) more.hidden = keep.length <= shown;
    if (preset) preset.value = [...preset.options].some((o) => o.value === `${sortKey}:${sortDir}`) ? `${sortKey}:${sortDir}` : preset.value;
  }

  table.querySelectorAll("th button[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      // First click: names A-Z, numbers high to low; clicking again flips it.
      sortDir = key === sortKey ? (sortDir === "asc" ? "desc" : "asc") : key === "name" ? "asc" : "desc";
      sortKey = key;
      shown = pageSize;
      apply();
    });
  });
  preset?.addEventListener("change", () => { [sortKey, sortDir] = preset.value.split(":"); shown = pageSize; apply(); });
  controls?.querySelectorAll("select:not([data-sort-preset]), input").forEach((el) =>
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
