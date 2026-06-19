"use strict";

const PALETTE = [
  "#ff9900", "#2e6fdb", "#16a34a", "#e11d48", "#7c3aed",
  "#0891b2", "#d97706", "#65a30d", "#db2777", "#475569",
];

function showError(message) {
  const banner = document.getElementById("error-banner");
  const text = document.getElementById("error-text");
  if (!banner || !text) {
    return;
  }
  text.textContent = message || "Something went wrong.";
  banner.classList.remove("hidden");
}

function readServiceData() {
  const el = document.getElementById("service-data");
  if (!el) {
    return {};
  }
  try {
    return JSON.parse(el.textContent) || {};
  } catch (err) {
    return {};
  }
}

function renderCharts() {
  if (typeof Chart === "undefined") {
    return;
  }
  const serviceData = readServiceData();
  const canvases = document.querySelectorAll("canvas.service-chart");

  canvases.forEach((canvas) => {
    const accountId = canvas.getAttribute("data-account-id");
    const services = serviceData[accountId] || [];
    if (!services.length) {
      const ctx = canvas.getContext("2d");
      ctx.font = "13px sans-serif";
      ctx.fillStyle = "#6b7785";
      ctx.textAlign = "center";
      ctx.fillText("No service data", canvas.width / 2, canvas.height / 2);
      return;
    }

    const labels = services.map((s) => s.service);
    const amounts = services.map((s) => s.amount);
    const colors = labels.map((_, i) => PALETTE[i % PALETTE.length]);

    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{ data: amounts, backgroundColor: colors, borderWidth: 1 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        },
      },
    });
  });
}

function wireRefresh() {
  const btn = document.getElementById("refresh-btn");
  if (!btn) {
    return;
  }
  btn.addEventListener("click", async () => {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Refreshing…";
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      const payload = await res.json();
      if (payload && payload.ok) {
        window.location.reload();
        return;
      }
      showError(payload && payload.error ? payload.error : "Refresh failed.");
    } catch (err) {
      showError("Refresh request failed: " + err.message);
    }
    btn.disabled = false;
    btn.textContent = original;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  renderCharts();
  wireRefresh();
});
