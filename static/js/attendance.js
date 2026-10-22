"use strict";
(() => {
  const form = document.getElementById("attendance-register-form");
  if (form) {
    form.addEventListener("submit", (event) => {
      const action = event.submitter?.dataset.attendanceAction || "draft";
      form.querySelector('[name="action"]').value = action;
      if (action === "final" && !window.confirm("Finalize this complete attendance register? Further changes require an approved correction.")) event.preventDefault();
    });
    document.querySelector("[data-mark-all-present]")?.addEventListener("click", () => {
      if (!window.confirm("Mark all draft rows present and clear arrival times? Approved leave and school closures will be preserved.")) return;
      form.querySelectorAll('select[name$="-status"]').forEach((select) => {
        if (["leave", "closure"].includes(select.value)) return;
        select.value = "present";
        const arrival = select.closest("tr").querySelector('input[name$="-arrival_time"]');
        if (arrival) arrival.value = "";
      });
    });
  }
  const data = document.getElementById("attendance-chart-data");
  if (!data || !window.Chart) return;
  const chart = JSON.parse(data.textContent);
  const base = {responsive: true, maintainAspectRatio: false, animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches};
  const daily = document.getElementById("attendance-daily-chart");
  if (daily && chart.daily?.length) new Chart(daily, {type: "bar", data: {labels: chart.daily.map(row => row.label), datasets: [
    {label: "Present", data: chart.daily.map(row => row.present), backgroundColor: "#416b5a"},
    {label: "Absent", data: chart.daily.map(row => row.absent), backgroundColor: "#bc7972"},
    {label: "Late", data: chart.daily.map(row => row.late), backgroundColor: "#c5a15a"}
  ]}, options: {...base, scales: {y: {beginAtZero: true, ticks: {precision: 0}}}}});
  const monthly = document.getElementById("attendance-monthly-chart");
  if (monthly && chart.monthly?.length) new Chart(monthly, {type: "line", data: {labels: chart.monthly.map(row => row.label), datasets: [{label: "Attendance %", data: chart.monthly.map(row => row.percentage), borderColor: "#416b5a", backgroundColor: "#e8efdc", fill: true, tension: .2}]}, options: {...base, scales: {y: {min: 0, max: 100}}}});
})();
