"use strict";
(() => {
  const toggle = document.querySelector("[data-toggle-sidebar]");
  const close = document.querySelector("[data-close-sidebar]");
  const sidebar = document.getElementById("sidebar");
  const main = document.querySelector(".main-column");
  const mobile = window.matchMedia("(max-width: 991px)");
  function syncFocus(open) {
    if (sidebar) sidebar.inert = mobile.matches && !open;
    if (main) main.inert = mobile.matches && open;
  }
  function setMenu(open) {
    document.body.classList.toggle("nav-open", open);
    toggle?.setAttribute("aria-expanded", String(open));
    if (close) close.hidden = !open;
    syncFocus(open);
    if (open) sidebar?.querySelector("a")?.focus();
    else toggle?.focus();
  }
  toggle?.addEventListener("click", () => setMenu(!document.body.classList.contains("nav-open")));
  close?.addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) setMenu(false);
    if (event.key === "Tab" && document.body.classList.contains("nav-open")) {
      const links = [...sidebar.querySelectorAll("a, button")];
      if (event.shiftKey && document.activeElement === links[0]) {
        links.at(-1)?.focus(); event.preventDefault();
      } else if (!event.shiftKey && document.activeElement === links.at(-1)) {
        links[0]?.focus(); event.preventDefault();
      }
    }
  });
  mobile.addEventListener("change", () => {
    document.body.classList.remove("nav-open");
    toggle?.setAttribute("aria-expanded", "false");
    if (close) close.hidden = true;
    syncFocus(false);
  });
  syncFocus(false);
  document.querySelectorAll("[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("[data-loading-label]");
      if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.textContent = button.dataset.loadingLabel;
      }
    });
  });
})();
