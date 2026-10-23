"use strict";
(() => {
  if (!window.Chart) return;
  function trend(canvasId, dataId, label, labels) {
    const canvas = document.getElementById(canvasId);
    const node = document.getElementById(dataId);
    if (!canvas || !node) return;
    const rows = JSON.parse(node.textContent);
    new Chart(canvas, {
      type: "line",
      data: { labels: rows.map(labels), datasets: [{
        label, data: rows.map(row => row.percentage === null ? null : Number(row.percentage)),
        borderColor: "#42673d", backgroundColor: "#e9efdf", pointRadius: 4,
        borderWidth: 2, tension: 0.15, spanGaps: false,
      }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        scales: { y: { min: 0, max: 100, title: { display: true, text: "Percent" } } },
        plugins: { legend: { display: false } },
      },
    });
  }
  trend("academic-progress", "academic-progress-data", "Published percentage", row => row.label);
  trend("attendance-trend", "attendance-trend-data", "Attendance percentage", row => row.month.slice(0, 7));
})();
