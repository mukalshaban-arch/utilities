/* Thin wrappers over Chart.js with a shared, colour-blind-friendly palette.
   Data is embedded in each page as JSON; these helpers just draw it. */
(function () {
  const PALETTE = [
    "#4e79a7", "#59a14f", "#f28e2b", "#e15759",
    "#76b7b2", "#edc948", "#b07aa1", "#ff9da7",
  ];

  const UGX = (v) => "UGX " + Math.round(v).toLocaleString("en-US");

  Chart.defaults.font.family =
    "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  // Theme-neutral so charts stay legible in both light and dark mode.
  Chart.defaults.color = "#64748b";
  Chart.defaults.borderColor = "rgba(148,163,184,.25)";

  function moneyAxis() {
    return {
      beginAtZero: true,
      ticks: { callback: (v) => UGX(v) },
    };
  }

  function moneyTooltip() {
    return { callbacks: { label: (c) => `${c.dataset.label || c.label}: ${UGX(c.parsed.y ?? c.parsed)}` } };
  }

  // Categorical breakdown as a doughnut (shares of a whole).
  window.doughnut = function (canvasId, labels, values) {
    const el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data: values, backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]) }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right" },
          tooltip: { callbacks: { label: (c) => `${c.label}: ${UGX(c.parsed)}` } },
        },
      },
    });
  };

  // Single-series bar (e.g. allocation per beneficiary).
  window.bar = function (canvasId, labels, values, label) {
    const el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      type: "bar",
      data: {
        labels,
        datasets: [{ label, data: values, backgroundColor: PALETTE[0] }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: moneyTooltip() },
        scales: { y: moneyAxis() },
      },
    });
  };

  // Grouped bars and/or lines across a shared x-axis (e.g. quarterly trend).
  // series: [{ label, values, type }]  (type defaults to "bar")
  window.multiSeries = function (canvasId, labels, series) {
    const el = document.getElementById(canvasId);
    if (!el) return;
    new Chart(el, {
      data: {
        labels,
        datasets: series.map((s, i) => ({
          type: s.type || "bar",
          label: s.label,
          data: s.values,
          backgroundColor: PALETTE[i % PALETTE.length],
          borderColor: PALETTE[i % PALETTE.length],
          borderWidth: s.type === "line" ? 2 : 0,
          fill: false,
          tension: 0.25,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { tooltip: moneyTooltip() },
        scales: { y: moneyAxis() },
      },
    });
  };
})();
