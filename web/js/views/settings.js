/* Settings view - buildings, staff accounts, activity log, data export. */

const SettingsView = {
  async render(container) {
    const boot = await App.bootData();
    container.innerHTML = `
      <div class="topbar"><h1>Settings</h1></div>

      <div class="card">
        <h2>Buildings</h2>
        <p class="muted small">Group residents by building or unit.</p>
        <div id="b-list"></div>
        <div class="btn-row mt">
          <button class="btn primary" id="b-add">&#10133; Add building</button>
        </div>
      </div>

      <div class="card">
        <h2>Staff accounts</h2>
        <p class="muted small">Everyone signs in with their own account so the activity log shows who did what.</p>
        <div id="u-list"></div>
        <div class="btn-row mt">
          <button class="btn primary" id="u-add">&#10133; Add account</button>
          <button class="btn" id="u-pass">&#128273; Change my password</button>
        </div>
      </div>

      <div class="card">
        <h2>Backup & data</h2>
        <p class="muted small">
          The database file lives at <code>data/ticket_tracker.db</code>. Copy that file to back up.
          Older tickets are never deleted automatically, so records stay available for review.
        </p>
        <div class="btn-row">
          <button class="btn" id="exp-csv">&#11015; Export a day of tickets (CSV)</button>
          <button class="btn" id="exp-json">&#11015; Download full backup (JSON)</button>
        </div>
      </div>

      <div class="card">
        <h2>Recent activity</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody id="a-rows"></tbody>
          </table>
        </div>
      </div>`;

    const renderBuildings = async () => {
      const data = await Api.get("/api/buildings");
      const list = container.querySelector("#b-list");
      list.innerHTML = data.buildings.length
        ? data.buildings.map((b) => `
          <div class="item-row" style="margin-bottom:6px">
            <span class="nm"><b>${UI.esc(b.name)}</b> <span class="muted small">${b.resident_count} residents</span></span>
            <button class="btn small" data-bedit="${b.id}">Rename</button>
            <button class="btn small danger" data-bdel="${b.id}">Delete</button>
          </div>`).join("")
        : `<p class="muted">No buildings yet.</p>`;
      list.querySelectorAll("[data-bedit]").forEach((btn) =>
        btn.addEventListener("click", () => {
          const b = data.buildings.find((x) => x.id === Number(btn.dataset.bedit));
          const name = prompt("Building name:", b.name);
          if (name && name.trim()) {
            Api.patch(`/api/buildings/${b.id}`, { name: name.trim() })
              .then(() => { App.bootData(true); renderBuildings(); })
              .catch((e) => UI.toast(e.message, "error"));
          }
        }));
      list.querySelectorAll("[data-bdel]").forEach((btn) =>
        btn.addEventListener("click", () => {
          if (!UI.confirm("Delete this building? Residents keep their data but lose the building label.")) return;
          Api.del(`/api/buildings/${btn.dataset.bdel}`)
            .then(() => { App.bootData(true); renderBuildings(); })
            .catch((e) => UI.toast(e.message, "error"));
        }));
    };

    const renderUsers = async () => {
      if (App.user.role !== "admin") {
        container.querySelector("#u-list").innerHTML = `<p class="muted">Only administrators can manage accounts.</p>`;
        container.querySelector("#u-add").classList.add("hidden");
        return;
      }
      const data = await Api.get("/api/users");
      const list = container.querySelector("#u-list");
      list.innerHTML = data.users.map((u) => `
        <div class="item-row" style="margin-bottom:6px">
          <span class="nm"><b>${UI.esc(u.display_name || u.username)}</b> <span class="muted small">${UI.esc(u.username)} &middot; ${UI.esc(u.role)}</span></span>
          ${u.id === App.user.id ? "" : `<button class="btn small danger" data-udel="${u.id}">Remove</button>`}
        </div>`).join("");
      list.querySelectorAll("[data-udel]").forEach((btn) =>
        btn.addEventListener("click", () => {
          if (!UI.confirm("Remove this account?")) return;
          Api.del(`/api/users/${btn.dataset.udel}`)
            .then(renderUsers)
            .catch((e) => UI.toast(e.message, "error"));
        }));
    };

    container.querySelector("#b-add").addEventListener("click", () => {
      const name = prompt("Building name:");
      if (name && name.trim()) {
        Api.post("/api/buildings", { name: name.trim() })
          .then(() => { App.bootData(true); renderBuildings(); })
          .catch((e) => UI.toast(e.message, "error"));
      }
    });
    container.querySelector("#u-add").addEventListener("click", () => {
      const body = document.createElement("div");
      body.innerHTML = `
        <label class="field">Name
          <input type="text" id="nu-name">
        </label>
        <label class="field">Username
          <input type="text" id="nu-user">
        </label>
        <label class="field">Password <span class="hint">At least 8 characters</span>
          <input type="password" id="nu-pass">
        </label>
        <label class="field">Role
          <select id="nu-role"><option value="staff">Staff</option><option value="admin">Administrator</option></select>
        </label>`;
      UI.modal({
        title: "Add staff account",
        body,
        actions: [
          {
            label: "Create",
            kind: "primary",
            onClick: async () => {
              try {
                await Api.post("/api/users", {
                  display_name: body.querySelector("#nu-name").value.trim(),
                  username: body.querySelector("#nu-user").value.trim(),
                  password: body.querySelector("#nu-pass").value,
                  role: body.querySelector("#nu-role").value,
                });
                UI.closeModal();
                UI.toast("Account created", "success");
                renderUsers();
              } catch (err) { UI.toast(err.message, "error"); }
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    });
    container.querySelector("#u-pass").addEventListener("click", () => {
      const pass = prompt("New password (at least 8 characters):");
      if (pass) {
        Api.post(`/api/users/${App.user.id}/password`, { password: pass })
          .then(() => UI.toast("Password changed", "success"))
          .catch((e) => UI.toast(e.message, "error"));
      }
    });

    container.querySelector("#exp-csv").addEventListener("click", () => {
      const date = prompt("Date to export (YYYY-MM-DD):", UI.todayIso());
      if (date) window.location.href = `/api/export.csv?date_from=${date}&date_to=${date}`;
    });
    container.querySelector("#exp-json").addEventListener("click", async () => {
      try {
        const [buildings, residents, items, tickets] = await Promise.all([
          Api.get("/api/buildings"),
          Api.get("/api/residents?active=all"),
          Api.get("/api/items"),
          Api.get(`/api/tickets?date_from=2000-01-01&date_to=2099-01-01`),
        ]);
        const blob = new Blob(
          [JSON.stringify({ exported: new Date().toISOString(), buildings: buildings.buildings, residents: residents.residents, items: items.items, tickets: tickets.tickets }, null, 2)],
          { type: "application/json" }
        );
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `ticket-tracker-backup-${UI.todayIso()}.json`;
        a.click();
        UI.toast("Backup downloaded", "success");
      } catch (err) { UI.toast(err.message, "error"); }
    });

    await renderBuildings();
    await renderUsers();
    try {
      const audit = await Api.get("/api/audit");
      container.querySelector("#a-rows").innerHTML = audit.entries.map((e) => `
        <tr>
          <td class="small">${UI.esc((e.created_at || "").replace("T", " ").slice(0, 16))}</td>
          <td class="small">${UI.esc(e.user_name || "")}</td>
          <td class="small">${UI.esc(e.action)}</td>
          <td class="small muted">${UI.esc(e.detail || "")}</td>
        </tr>`).join("") || `<tr><td colspan="4" class="muted">No activity yet.</td></tr>`;
    } catch (err) { /* non-admins may still see it; ignore */ }
  },
};
