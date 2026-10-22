"use strict";
(() => {
  document.querySelectorAll("[data-exam-print]").forEach(button => button.addEventListener("click", () => window.print()));
  document.querySelectorAll("form[data-exam-confirm]").forEach(form => form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.examConfirm)) event.preventDefault();
  }));
  const marks = document.getElementById("exam-marks-form");
  marks?.addEventListener("submit", event => {
    const action = event.submitter?.dataset.examAction || "draft";
    marks.querySelector('[name="action"]').value = action;
    if (action === "submit" && !window.confirm("Submit every student's assessment status for independent review? Submitted marks are protected.")) { event.preventDefault(); return; }
    const status = marks.querySelector("[data-exam-saving]");
    if (status) status.textContent = "Saving marks…";
  });
  document.querySelector("[data-exam-search]")?.addEventListener("input", event => {
    const query = event.target.value.toLocaleLowerCase().trim();
    document.querySelectorAll("[data-exam-row]").forEach(row => row.hidden = !row.textContent.toLocaleLowerCase().includes(query));
  });
  if (!window.Chart) return;
  const options = {responsive:true, maintainAspectRatio:false, animation:!window.matchMedia("(prefers-reduced-motion: reduce)").matches};
  const source = document.getElementById("exam-chart-data");
  if (source) {
    const data = JSON.parse(source.textContent);
    const subjects = document.getElementById("exam-subject-chart");
    if (subjects) new Chart(subjects, {type:"bar", data:{labels:data.subjects.map(row=>row.label),datasets:[{label:"Average %",data:data.subjects.map(row=>Number(row.average)),backgroundColor:"#55745b",borderRadius:5}]}, options:{...options,scales:{y:{min:0,max:100}}}});
    const grades = document.getElementById("exam-grade-chart");
    if (grades) new Chart(grades, {type:"doughnut", data:{labels:data.grades.map(row=>row.label),datasets:[{label:"Published results",data:data.grades.map(row=>row.count),backgroundColor:["#3f6149","#8da46d","#bed19a","#dacb91","#c79677","#ab7970"]}]}, options});
  }
  const progress = document.getElementById("exam-progress-data");
  if (progress) {
    const data = JSON.parse(progress.textContent);
    const canvas = document.getElementById("exam-progress-chart");
    new Chart(canvas,{type:"line",data:{labels:data.map(row=>row.label),datasets:[{label:"Published percentage",data:data.map(row=>Number(row.percentage)),borderColor:"#41674d",backgroundColor:"#e5eddb",fill:true,tension:.1}]},options:{...options,scales:{y:{min:0,max:100}}}});
  }
})();
