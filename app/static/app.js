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
