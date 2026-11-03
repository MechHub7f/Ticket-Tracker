/* Shared UI helpers: toasts, modals, escaping, chips. */

const UI = {
  esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&" + "amp;")
      .replaceAll("<", "&" + "lt;")
      .replaceAll(">", "&" + "gt;")
      .replaceAll('"', "&" + "quot;")
      .replaceAll("'", "&" + "#39;");
  },

  toast(message, kind = "") {
    const box = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 6000 : 3200);
  },

  modal({ title, body, wide, onOpen, actions }) {
    const holder = document.getElementById("modals");
    holder.innerHTML = "";
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    const actionsHtml = (actions || [])
      .map((a, i) => `<button class="btn ${a.kind || ""}" data-act="${i}">${UI.esc(a.label)}</button>`)
      .join("");
    backdrop.innerHTML = `
      <div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>${UI.esc(title)}</h2>
          <button class="btn small" data-close="1" aria-label="Close">&#10005;</button>
        </div>
        <div class="modal-body"></div>
        ${actionsHtml ? `<div class="modal-foot">${actionsHtml}</div>` : ""}
      </div>`;
    holder.appendChild(backdrop);
    const bodyEl = backdrop.querySelector(".modal-body");
    if (typeof body === "string") bodyEl.innerHTML = body;
    else if (body) bodyEl.appendChild(body);

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop || e.target.closest("[data-close]")) UI.closeModal();
    });
    (actions || []).forEach((action, i) => {
      backdrop.querySelector(`[data-act="${i}"]`).addEventListener("click", () => action.onClick());
    });
    if (onOpen) onOpen(backdrop);
    return backdrop;
  },

  closeModal() {
    document.getElementById("modals").innerHTML = "";
  },

  chips(list, kind = "") {
    return (list || [])
      .map((t) => `<span class="chip ${kind}">${UI.esc(t)}</span>`)
      .join("");
  },

  allergyChips(resident) {
    const allergyList = String(resident.allergies || "").split(/[,;]/).map((s) => s.trim()).filter(Boolean);
    const dietList = String(resident.diet || "").split(/[,;]/).map((s) => s.trim()).filter(Boolean);
    return (
      UI.chips(allergyList, "allergy") +
      UI.chips(dietList, "diet")
    );
  },

  statusChip(status, labels) {
    const label = labels && labels[status] ? labels[status] : status;
    const kind = { ready: "muted", delivered: "ok", cancelled: "warn", open: "" }[status] || "";
    return `<span class="chip ${kind}">${UI.esc(label)}</span>`;
  },

  fmtDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  },

  niceDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  },

  todayIso() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  },

  shiftDate(iso, days) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + days);
    return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  },

  confirm(message) {
    return window.confirm(message);
  },

  empty(message, icon = "&#128203;") {
    return `<div class="empty-state"><div class="big">${icon}</div><p>${UI.esc(message)}</p></div>`;
  },
};
