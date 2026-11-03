/* Residents view - names, buildings, allergies, diet restrictions, notes. */

const ResidentsView = {
  state: null,

  defaults() {
    return { q: "", building_id: 0, showInactive: false, residents: [] };
  },

  async render(container) {
    if (!this.state) this.state = this.defaults();
    const s = this.state;
    const boot = await App.bootData();
    this.boot = boot;

    const isAdmin = boot.user && boot.user.role === "admin";

    container.innerHTML = `
      <div class="topbar">
        <h1>Residents</h1>
        <div class="actions">
          ${isAdmin ? `<button class="btn primary" id="btn-add">&#10133; Add resident</button>` : ""}
        </div>
      </div>
      <div class="filters">
        <label class="field search">Search
          <input type="text" id="r-q" placeholder="Name, room, allergy&hellip;">
        </label>
        <label class="field">Building
          <select id="r-building">
            <option value="0">All buildings</option>
            ${boot.buildings.map((b) => `<option value="${b.id}">${UI.esc(b.name)}</option>`).join("")}
          </select>
        </label>
        ${isAdmin ? `
        <label class="field" style="align-self:center">
          <span style="display:flex;gap:8px;align-items:center;font-weight:400">
            <input type="checkbox" id="r-inactive"> Show inactive
          </span>
        </label>` : ""}
      </div>
      <div class="card table-wrap">
        <table>
          <thead><tr>
            <th>Name</th><th>Building</th><th>Room</th><th>Consent</th><th>Allergies</th><th>Diet restrictions</th><th>Notes</th><th></th>
          </tr></thead>
          <tbody id="r-rows"></tbody>
        </table>
      </div>`;

    const f = (id) => container.querySelector(id);
    f("#r-q").value = s.q;
    f("#r-building").value = s.building_id;
    f("#r-inactive").checked = s.showInactive;

    let timer = null;
    f("#r-q").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { s.q = f("#r-q").value; this.refresh(); }, 250);
    });
    f("#r-building").addEventListener("change", () => { s.building_id = Number(f("#r-building").value); this.refresh(); });
    f("#r-inactive").addEventListener("change", () => { s.showInactive = f("#r-inactive").checked; this.refresh(); });
    f("#btn-add").addEventListener("click", () => this.editModal(null));

    await this.refresh();
  },

  async refresh() {
    const s = this.state;
    const params = new URLSearchParams();
    if (s.q) params.set("q", s.q);
    if (s.building_id) params.set("building_id", s.building_id);
    params.set("active", s.showInactive ? "all" : "1");
    try {
      const data = await Api.get(`/api/residents?${params}`);
      s.residents = data.residents;
      this.paint();
    } catch (err) {
      UI.toast(err.message, "error");
    }
  },

  paint() {
    const rows = document.getElementById("r-rows");
    const s = this.state;
    const isAdmin = this.boot.user && this.boot.user.role === "admin";
    if (!s.residents.length) {
      rows.innerHTML = `<tr><td colspan="8">${UI.empty("No residents found. Add your first resident to get started.", "&#128100;")}</td></tr>`;
      return;
    }
    rows.innerHTML = s.residents.map((r) => `
      <tr>
        <td><b>${UI.esc(r.name)}</b>${r.active ? "" : " <span class=\"chip warn\">Inactive</span>"}</td>
        <td>${UI.esc(r.building_name || "")}</td>
        <td>${UI.esc(r.room || "")}</td>
        <td>${r.consent_date ? `<span class="chip ok">${UI.esc(r.consent_date)}</span>` : `<span class="chip warn">Missing</span>`}</td>
        <td>${UI.chips(String(r.allergies || "").split(/[,;]/).map((x) => x.trim()).filter(Boolean), "allergy")}</td>
        <td>${UI.chips(String(r.diet || "").split(/[,;]/).map((x) => x.trim()).filter(Boolean), "diet")}</td>
        <td class="small muted">${UI.esc(r.notes || "")}</td>
        <td class="actions">
          ${isAdmin ? `
          <button class="btn small" data-edit="${r.id}">Edit</button>
          <button class="btn small danger" data-del="${r.id}" data-name="${UI.esc(r.name)}">Delete</button>` : ""}
        </td>
      </tr>`).join("");

    rows.querySelectorAll("[data-edit]").forEach((btn) =>
      btn.addEventListener("click", () => this.editModal(s.residents.find((r) => r.id === Number(btn.dataset.edit)))));
    rows.querySelectorAll("[data-del]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        if (!UI.confirm(`Delete resident "${btn.dataset.name}" and all of their tickets? This cannot be undone.`)) return;
        try {
          await Api.del(`/api/residents/${btn.dataset.del}`);
          UI.toast("Resident deleted", "success");
          this.refresh();
        } catch (err) { UI.toast(err.message, "error"); }
      }));
  },

  editModal(resident) {
    const boot = this.boot;
    const isNew = !resident;
    const r = resident || { name: "", building_id: "", room: "", allergies: "", diet: "", notes: "", active: 1, consent_date: "" };
    const body = document.createElement("div");
    body.innerHTML = `
      <label class="field">Full name
        <input type="text" id="er-name" value="${UI.esc(r.name)}" autocomplete="off">
      </label>
      <div class="grid-2">
        <label class="field">Building
          <select id="er-building">
            <option value="">None</option>
            ${boot.buildings.map((b) => `<option value="${b.id}" ${r.building_id === b.id ? "selected" : ""}>${UI.esc(b.name)}</option>`).join("")}
          </select>
        </label>
        <label class="field">Room
          <input type="text" id="er-room" value="${UI.esc(r.room || "")}">
        </label>
      </div>
      <label class="field">Consent date <span class="hint">Required before allergies or diet restrictions can be recorded (family/physician consent on file)</span>
        <input type="date" id="er-consent" value="${UI.esc(r.consent_date || "")}">
      </label>
      <label class="field">Allergies <span class="hint">Separate with commas, e.g. "Peanuts, shellfish"</span>
        <input type="text" id="er-allergies" value="${UI.esc(r.allergies || "")}">
      </label>
      <label class="field">Diet restrictions <span class="hint">e.g. "Low sodium, diabetic, pureed"</span>
        <input type="text" id="er-diet" value="${UI.esc(r.diet || "")}">
      </label>
      <label class="field">Notes <span class="hint">Shows on every ticket for this resident</span>
        <textarea id="er-notes">${UI.esc(r.notes || "")}</textarea>
      </label>
      ${isNew ? "" : `<label class="field" style="font-weight:400"><input type="checkbox" id="er-active" ${r.active ? "checked" : ""}> Active resident</label>`}`;

    UI.modal({
      title: isNew ? "Add resident" : `Edit ${resident.name}`,
      body,
      actions: [
        {
          label: "Save",
          kind: "primary",
          onClick: async () => {
            const data = {
              name: body.querySelector("#er-name").value.trim(),
              building_id: body.querySelector("#er-building").value || null,
              room: body.querySelector("#er-room").value.trim(),
              consent_date: body.querySelector("#er-consent").value || "",
              allergies: body.querySelector("#er-allergies").value.trim(),
              diet: body.querySelector("#er-diet").value.trim(),
              notes: body.querySelector("#er-notes").value.trim(),
            };
            if (!isNew) data.active = body.querySelector("#er-active").checked ? 1 : 0;
            if (!data.name) { UI.toast("Name is required", "error"); return; }
            try {
              if (isNew) await Api.post("/api/residents", data);
              else await Api.patch(`/api/residents/${resident.id}`, data);
              UI.closeModal();
              UI.toast(isNew ? "Resident added" : "Saved", "success");
              this.refresh();
            } catch (err) { UI.toast(err.message, "error"); }
          },
        },
        { label: "Cancel", onClick: () => UI.closeModal() },
      ],
    });
  },
};
