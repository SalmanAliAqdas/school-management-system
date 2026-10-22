"use strict";
(() => {
  const element = document.getElementById("enrollment-data");
  const canvas = document.getElementById("enrollment-chart");
  if (!element || !canvas || !window.Chart) return;
  const rows = JSON.parse(element.textContent);
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((row) => row.section__school_class__name),
      datasets: [{
        label: "Students", data: rows.map((row) => row.total),
        backgroundColor: ["#416b5a", "#b1c995", "#d7dfb3", "#d9bfa4", "#99b8ac"],
        borderRadius: 6, maxBarThickness: 56,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      plugins: {legend: {display: false}, tooltip: {displayColors: false}},
      scales: {
        x: {grid: {display: false}, border: {display: false}, ticks: {color: "#6c7973"}},
        y: {beginAtZero: true, ticks: {precision: 0, color: "#6c7973"}, border: {display: false}, grid: {color: "#edf0eb"}},
      },
    },
  });
})();
