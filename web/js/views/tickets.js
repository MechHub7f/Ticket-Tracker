/* Tickets view - the heart of the app. Supports bulk add / remove / replace
   across many tickets at once, with allergy and diet guardrails. */

const TicketsView = {
  state: null,

  defaults() {
    return {
      filters: {
        date: UI.todayIso(),
        meal: "",
        building_id: 0,
        status: "",
        q: "",
      },
      tickets: [],
      selected: new Set(),
      stats: null,
      loaded: false,
    };
  },

  async render(container) {
    if (!this.state) this.state = this.defaults();
    const boot = await App.bootData();
    this.boot = boot;
    const s = this.state;

    container.innerHTML = `
      <div class="topbar">
        <h1>Tickets</h1>
        <div class="actions">
          <button class="btn" id="btn-generate">&#128197; Generate&hellip;</button>
          <button class="btn" id="btn-export">&#11015; CSV</button>
        </div>
      </div>
      <div id="ticket-stats"></div>
      <div class="filters">
        <label class="field">Date
          <input type="date" id="f-date" value="${s.filters.date}">
        </label>
        <label class="field">Meal
          <select id="f-meal">
            <option value="">All meals</option>
            ${boot.meals.map((m) => `<option value="${m.value}">${UI.esc(m.label)}</option>`).join("")}
          </select>
        </label>
        <label class="field">Building
          <select id="f-building">
            <option value="0">All buildings</option>
            ${boot.buildings.map((b) => `<option value="${b.id}">${UI.esc(b.name)}</option>`).join("")}
          </select>
        </label>
        <label class="field">Status
          <select id="f-status">
            <option value="">Any status</option>
            ${boot.statuses.map((st) => `<option value="${st.value}">${UI.esc(st.label)}</option>`).join("")}
          </select>
        </label>
        <label class="field search">Search resident
          <input type="text" id="f-q" placeholder="Type a name&hellip;" value="${UI.esc(s.filters.q)}">
        </label>
      </div>
      <div id="select-bar"></div>
      <div id="ticket-list"></div>`;

    const f = (id) => container.querySelector(id);
    f("#f-date").value = s.filters.date;
    f("#f-meal").value = s.filters.meal;
    f("#f-building").value = s.filters.building_id;
    f("#f-status").value = s.filters.status;
    f("#f-q").value = s.filters.q;

    f("#f-date").addEventListener("change", () => {
      s.filters.date = f("#f-date").value || UI.todayIso();
      this.refresh(container);
    });
    ["#f-meal", "#f-building", "#f-status"].forEach((sel) => {
      f(sel).addEventListener("change", () => {
        s.filters.meal = f("#f-meal").value;
        s.filters.building_id = Number(f("#f-building").value);
        s.filters.status = f("#f-status").value;
        this.refresh(container);
      });
    });
    let searchTimer = null;
    f("#f-q").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        s.filters.q = f("#f-q").value;
        this.refresh(container);
      }, 300);
    });

    f("#btn-generate").addEventListener("click", () => this.generateModal(container));
    f("#btn-export").addEventListener("click", () => {
      const params = new URLSearchParams({ date_from: s.filters.date, date_to: s.filters.date });
      if (s.filters.building_id) params.set("building_id", s.filters.building_id);
      window.location.href = `/api/export.csv?${params}`;
    });

    await this.refresh(container);
  },

  async refresh(container) {
    const s = this.state;
    const params = new URLSearchParams({ date: s.filters.date });
    if (s.filters.meal) params.set("meal", s.filters.meal);
    if (s.filters.building_id) params.set("building_id", s.filters.building_id);
    if (s.filters.status) params.set("status", s.filters.status);
    if (s.filters.q) params.set("q", s.filters.q);

    try {
      const [list, stats] = await Promise.all([
        Api.get(`/api/tickets?${params}`),
        Api.get(`/api/stats?date=${s.filters.date}`),
      ]);
      s.tickets = list.tickets;
      s.stats = stats;
      s.selected = new Set([...s.selected].filter((id) => s.tickets.some((t) => t.id === id)));
      this.paint(container);
    } catch (err) {
      UI.toast(err.message, "error");
    }
  },

  paint(container) {
    const s = this.state;
    const boot = this.boot;
    const list = container.querySelector("#ticket-list");
    const statsEl = container.querySelector("#ticket-stats");
    const barEl = container.querySelector("#select-bar");

    const st = s.stats;
    statsEl.innerHTML = st ? `
      <div class="grid-4" style="margin-bottom:14px">
        <div class="stat"><div class="num">${st.total}</div><div class="label">Tickets for ${UI.esc(UI.fmtDate(st.date))}</div></div>
        <div class="stat"><div class="num">${st.by_status.open}</div><div class="label">Open</div></div>
        <div class="stat"><div class="num">${st.by_status.ready}</div><div class="label">Ready</div></div>
        <div class="stat"><div class="num">${st.by_status.delivered}</div><div class="label">Delivered</div></div>
      </div>` : "";

    if (!s.tickets.length) {
      list.innerHTML = UI.empty(
        `No tickets for ${UI.niceDate(s.filters.date)}${s.filters.meal ? ` (${boot.meal_labels[s.filters.meal] || s.filters.meal})` : ""}. Use "Generate" to create them.`,
        "&#128197;"
      );
      barEl.innerHTML = "";
      return;
    }

    // bulk bar
    const n = s.selected.size;
    barEl.innerHTML = `
      <label><input type="checkbox" id="sel-all" ${n === s.tickets.length ? "checked" : ""}> Select all (${s.tickets.length})</label>
      <span class="grow"></span>
      ${n ? `
        <span class="count">${n} selected</span>
        <button class="btn small primary" id="bulk-add">&#10133; Add items</button>
        <button class="btn small danger" id="bulk-remove">&#10134; Remove items</button>
        <button class="btn small" id="bulk-replace">&#128260; Replace</button>
        <button class="btn small" id="bulk-status">&#9989; Status</button>
        <button class="btn small" id="bulk-note">&#128221; Note</button>
        <button class="btn small" id="bulk-clear">Clear</button>` : `<span class="muted">Check tickets below to add or remove items on many tickets at once.</span>`}`;

    barEl.querySelector("#sel-all").addEventListener("change", (e) => {
      s.selected = e.target.checked ? new Set(s.tickets.map((t) => t.id)) : new Set();
      this.paint(container);
    });
    if (n) {
      barEl.querySelector("#bulk-add").addEventListener("click", () => this.bulkModal(container, "add"));
      barEl.querySelector("#bulk-remove").addEventListener("click", () => this.bulkModal(container, "remove"));
      barEl.querySelector("#bulk-replace").addEventListener("click", () => this.bulkModal(container, "replace"));
      barEl.querySelector("#bulk-status").addEventListener("click", () => this.bulkModal(container, "status"));
      barEl.querySelector("#bulk-note").addEventListener("click", () => this.bulkModal(container, "note"));
      barEl.querySelector("#bulk-clear").addEventListener("click", () => {
        s.selected = new Set();
        this.paint(container);
      });
    }

    list.innerHTML = `<div class="ticket-grid">${s.tickets.map((t) => this.ticketHtml(t)).join("")}</div>`;

    list.querySelectorAll(".ticket").forEach((card) => {
      const id = Number(card.dataset.id);
      const ticket = s.tickets.find((t) => t.id === id);

      card.querySelector(".pick").addEventListener("change", (e) => {
        if (e.target.checked) s.selected.add(id); else s.selected.delete(id);
        card.classList.toggle("selected", e.target.checked);
        // repaint just the bar
        this.paint(container);
      });

      card.querySelectorAll("[data-add]").forEach((btn) => btn.addEventListener("click", () => this.addOne(container, ticket, btn.dataset.add)));
      card.querySelectorAll("[data-minus]").forEach((btn) => btn.addEventListener("click", () => this.minusOne(container, ticket, btn.dataset.minus)));
      card.querySelectorAll("[data-remove]").forEach((btn) => btn.addEventListener("click", () => this.removeItemRow(container, ticket, Number(btn.dataset.remove))));
      card.querySelector("[data-additem]").addEventListener("click", async () => {
        const ids = await this.pickItems({ title: `Add item to ${ticket.resident_name}`, single: true });
        if (!ids.length) return;
        await this.callAndPaint(container, () =>
          Api.post(`/api/tickets/${id}/items`, { item_id: ids[0], qty: 1 })
        );
      });
      card.querySelectorAll("[data-status]").forEach((btn) => btn.addEventListener("click", () => this.cycleStatus(container, ticket, btn.dataset.status)));
      card.querySelector("[data-notes]").addEventListener("click", () => this.notesModal(container, ticket));
    });
  },

  ticketHtml(t) {
    const boot = this.boot;
    const s = this.state;
    const checked = s.selected.has(t.id) ? "checked" : "";
    const allergyHtml = UI.allergyChips(t);
    const nextStatus = { open: "ready", ready: "delivered", delivered: "open", cancelled: "open" }[t.status] || "open";
    const nextLabel = boot.status_labels[nextStatus] || nextStatus;
    const items = t.items.length
      ? t.items.map((i) => `
        <div class="item-row">
          <span class="qty">${i.qty}&times;</span>
          <span class="nm">${UI.esc(i.name)}</span>
          ${i.note ? `<span class="note-chip">${UI.esc(i.note)}</span>` : ""}
          <button class="small btn" data-minus="${i.item_id}" title="Remove one" aria-label="minus ${UI.esc(i.name)}">&minus;</button>
          <button class="small btn" data-add="${i.item_id}" title="Add one" aria-label="plus ${UI.esc(i.name)}">&#43;</button>
          <button class="x" data-remove="${i.item_id}" title="Remove entirely">&#10005;</button>
        </div>`).join("")
      : `<div class="empty-items">No items yet &mdash; use &#43; to add</div>`;

    return `
      <div class="ticket meal-${t.meal} status-${t.status} ${s.selected.has(t.id) ? "selected" : ""}" data-id="${t.id}">
        <div class="head">
          <input type="checkbox" class="pick" ${checked} aria-label="select ticket">
          <div class="who">
            <div class="name">${UI.esc(t.resident_name)}</div>
            <div class="sub">${UI.esc(t.building_name || "No building")}${t.room ? ` &middot; Room ${UI.esc(t.room)}` : ""} &middot; ${UI.esc(boot.meal_labels[t.meal] || t.meal)}</div>
          </div>
          <div>${UI.statusChip(t.status, boot.status_labels)}</div>
        </div>
        ${allergyHtml ? `<div class="warn-chips">${allergyHtml}</div>` : ""}
        <div class="items">${items}</div>
        <div class="note-box">
          ${t.notes ? `<b>Ticket:</b> ${UI.esc(t.notes)}<br>` : ""}
          ${t.resident_notes ? `<b>Resident:</b> ${UI.esc(t.resident_notes)}` : ""}
        </div>
        <div class="foot">
          <button class="small btn" data-additem>&#10133; Item</button>
          <button class="small btn" data-notes>&#128221; Notes</button>
          <button class="status-btn" data-status="${nextStatus}">Mark ${UI.esc(nextLabel)}</button>
        </div>
      </div>`;
  },

  // ------------------------------------------------------------ actions
  async callAndPaint(container, fn) {
    try {
      await fn();
      await this.refresh(container);
    } catch (err) {
      UI.toast(err.message, "error");
    }
  },

  async addOne(container, ticket, itemId) {
    await this.callAndPaint(container, () =>
      Api.post(`/api/tickets/${ticket.id}/items`, { item_id: Number(itemId), qty: 1 })
    );
  },

  async minusOne(container, ticket, itemId) {
    const row = ticket.items.find((i) => i.item_id === Number(itemId));
    if (!row) return;
    await this.callAndPaint(container, () =>
      Api.patch(`/api/tickets/${ticket.id}/items/${itemId}`, { qty: row.qty - 1 })
    );
  },

  async removeItemRow(container, ticket, itemId) {
    await this.callAndPaint(container, () =>
      Api.del(`/api/tickets/${ticket.id}/items/${itemId}`)
    );
  },

  async cycleStatus(container, ticket, status) {
    await this.callAndPaint(container, () =>
      Api.patch(`/api/tickets/${ticket.id}`, { status })
    );
  },

  notesModal(container, ticket) {
    const body = document.createElement("div");
    body.innerHTML = `
      <label class="field">Ticket notes <span class="hint">For this meal only (e.g. "tray to room 204")</span>
        <textarea id="nm-ticket">${UI.esc(ticket.notes)}</textarea>
      </label>
      <label class="field">Resident notes <span class="hint">Saved to the resident's profile &mdash; appears on every ticket</span>
        <textarea id="nm-resident">${UI.esc(ticket.resident_notes)}</textarea>
      </label>`;
    UI.modal({
      title: `Notes - ${ticket.resident_name}`,
      body,
      actions: [
        {
          label: "Save",
          kind: "primary",
          onClick: async () => {
            const ticketNotes = body.querySelector("#nm-ticket").value.trim();
            const residentNotes = body.querySelector("#nm-resident").value.trim();
            UI.closeModal();
            await this.callAndPaint(container, async () => {
              await Api.patch(`/api/tickets/${ticket.id}`, { notes: ticketNotes });
              const resident = await Api.get(`/api/residents/${ticket.resident_id}`);
              if ((resident.resident.notes || "") !== residentNotes) {
                await Api.patch(`/api/residents/${ticket.resident_id}`, { notes: residentNotes });
              }
            });
            UI.toast("Notes saved", "success");
          },
        },
        { label: "Cancel", onClick: () => UI.closeModal() },
      ],
    });
  },

  // ------------------------------------------------------- item picker
  pickItems({ title = "Choose items", single = false, preselected = [] } = {}) {
    return new Promise((resolve) => {
      const boot = this.boot;
      const chosen = new Set(preselected);
      let category = "";
      let search = "";

      const body = document.createElement("div");
      body.innerHTML = `
        <div class="picker">
          <div class="picker-filters">
            <input type="text" id="pk-search" placeholder="Search items&hellip;" style="flex:1;min-width:160px">
            <select id="pk-cat">
              <option value="">All categories</option>
              ${boot.categories.map((c) => `<option value="${UI.esc(c)}">${UI.esc(c)}</option>`).join("")}
            </select>
          </div>
          <div class="picker-list" id="pk-list"></div>
          ${single ? "" : `<p class="small muted" id="pk-count"></p>`}
        </div>`;

      const backdrop = UI.modal({
        title,
        body,
        wide: !single,
        actions: [
          {
            label: single ? "Use item" : `Add selected`,
            kind: "primary",
            onClick: () => { UI.closeModal(); resolve([...chosen]); },
          },
          { label: "Cancel", onClick: () => { UI.closeModal(); resolve([]); } },
        ],
        onOpen: () => {
          const paintList = () => {
            const q = search.toLowerCase();
            const rows = boot.items
              .filter((i) => (!category || i.category === category) && (!q || i.name.toLowerCase().includes(q) || String(i.tags || "").toLowerCase().includes(q)))
              .map((i) => `
                <label class="pick-row">
                  <input type="checkbox" data-id="${i.id}" ${chosen.has(i.id) ? "checked" : ""}>
                  <span><b>${UI.esc(i.name)}</b>${i.tags ? `<br><span class="tag-mini">${UI.esc(i.tags)}</span>` : ""}</span>
                  <span class="cat"><span class="chip muted">${UI.esc(i.category)}</span></span>
                </label>`).join("");
            body.querySelector("#pk-list").innerHTML = rows || `<div class="empty-state">No items match</div>`;
            const count = body.querySelector("#pk-count");
            if (count) count.textContent = `${chosen.size} selected`;
            body.querySelectorAll("[data-id]").forEach((input) => {
              input.addEventListener("change", () => {
                const id = Number(input.dataset.id);
                if (input.checked) {
                  if (single) {
                    chosen.clear();
                    body.querySelectorAll("[data-id]").forEach((o) => { if (o !== input) o.checked = false; });
                  }
                  chosen.add(id);
                } else {
                  chosen.delete(id);
                }
                const count2 = body.querySelector("#pk-count");
                if (count2) count2.textContent = `${chosen.size} selected`;
              });
            });
          };
          paintList();
          body.querySelector("#pk-search").addEventListener("input", (e) => { search = e.target.value; paintList(); });
          body.querySelector("#pk-cat").addEventListener("change", (e) => { category = e.target.value; paintList(); });
        },
      });
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) resolve([]);
      });
    });
  },

  // ------------------------------------------------------------ bulk
  bulkModal(container, mode) {
    const s = this.state;
    const boot = this.boot;
    const ticketIds = [...s.selected];
    if (!ticketIds.length) return;

    const body = document.createElement("div");

    if (mode === "add") {
      let qty = 1;
      body.innerHTML = `
        <p>Adding items to <b id="bm-count">${ticketIds.length}</b> tickets.</p>
        <label class="field">Quantity per ticket
          <input type="number" id="bm-qty" value="1" min="1" max="50">
        </label>
        <div id="bm-picker"></div>
        <div id="bm-preview"></div>`;
      let chosenItems = [];
      let previewConflicts = 0;
      const mountPicker = async () => {
        const ids = await this.pickItems({ title: "Items to add to every selected ticket" });
        if (!ids.length) return;
        chosenItems = ids;
        const preview = body.querySelector("#bm-preview");
        preview.innerHTML = `<p class="muted">Checking for allergy and diet conflicts&hellip;</p>`;
        try {
          const result = await Api.post("/api/bulk/add", {
            ticket_ids: ticketIds,
            item_ids: chosenItems,
            qty: Number(body.querySelector("#bm-qty").value || 1),
            dry_run: true,
          });
          const conflicts = result.conflicts || [];
          preview.innerHTML = `
            <div class="summary-box">
              Will add <b>${result.items}</b> item${result.items === 1 ? "" : "s"} across <b>${result.tickets}</b> tickets.
            </div>
            ${conflicts.length ? `
            <div class="conflict-box">
              <div class="conflict-title">&#9888; ${conflicts.length} allergy/diet conflict${conflicts.length === 1 ? "" : "s"} found</div>
              <ul>${conflicts.map((c) => `<li>${UI.esc(c.ticket)} &mdash; ${UI.esc(c.resident)}: ${UI.esc(c.reason)}</li>`).join("")}</ul>
              <p class="small">Conflicting tickets are skipped unless you confirm below. Overrides are recorded in the audit log.</p>
            </div>` : ""}`;
          previewConflicts = conflicts.length;
          return { conflicts: conflicts.length };
        } catch (err) {
          preview.innerHTML = "";
          UI.toast(err.message, "error");
          return { conflicts: 0 };
        }
      };
      const backdrop = UI.modal({
        title: `Add items to ${ticketIds.length} tickets`,
        body,
        wide: true,
        actions: [
          {
            label: "Pick items&hellip;",
            onClick: async () => {
              const res = await mountPicker();
              if (res && res.conflicts) {
                const applyBtn = backdrop.querySelector('[data-act="1"]');
                applyBtn.textContent = `Apply anyway (${res.conflicts} conflicts)`;
              }
            },
          },
          {
            label: "Apply",
            kind: "primary",
            onClick: async () => {
              if (!chosenItems.length) { UI.toast("Pick items first"); return; }
              const qtyVal = Number(body.querySelector("#bm-qty").value || 1);
              UI.closeModal();
              await this.runBulk(container, () => Api.post("/api/bulk/add", {
                ticket_ids: ticketIds, item_ids: chosenItems, qty: qtyVal, force: previewConflicts > 0,
              }));
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    }

    if (mode === "remove") {
      body.innerHTML = `
        <p>Removing items from <b>${ticketIds.length}</b> tickets.</p>
        <div class="btn-row" style="margin-bottom:10px">
          <button class="btn" id="bm-pick">&#128269; Choose items to remove&hellip;</button>
        </div>
        <div id="bm-chosen" class="muted">Nothing chosen yet.</div>
        <label class="field mt"><input type="checkbox" id="bm-all"> Remove <b>every item</b> from the selected tickets (clear them completely)</label>`;
      let chosenItems = [];
      body.querySelector("#bm-pick").addEventListener("click", async () => {
        const ids = await this.pickItems({ title: "Items to remove from every selected ticket" });
        chosenItems = ids;
        const names = ids.map((id) => {
          const item = boot.items.find((i) => i.id === id);
          return item ? item.name : `#${id}`;
        });
        body.querySelector("#bm-chosen").innerHTML = names.length
          ? `Will remove: <b>${UI.esc(names.join(", "))}</b>`
          : "Nothing chosen yet.";
      });
      UI.modal({
        title: `Remove items from ${ticketIds.length} tickets`,
        body,
        wide: true,
        actions: [
          {
            label: "Remove",
            kind: "danger",
            onClick: async () => {
              const removeAll = body.querySelector("#bm-all").checked;
              if (!removeAll && !chosenItems.length) { UI.toast("Choose items first or tick 'remove every item'"); return; }
              UI.closeModal();
              await this.runBulk(container, () => Api.post("/api/bulk/remove", {
                ticket_ids: ticketIds,
                item_ids: removeAll ? [] : chosenItems,
                remove_all: removeAll,
              }));
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    }

    if (mode === "replace") {
      let replaceConflicts = 0;
      body.innerHTML = `
        <p>Swap one item for another on all selected tickets.</p>
        <label class="field">Replace this item
          <select id="bm-from">
            <option value="">Choose&hellip;</option>
            ${boot.items.map((i) => `<option value="${i.id}">${UI.esc(i.name)}</option>`).join("")}
          </select>
        </label>
        <label class="field">With this item
          <select id="bm-to">
            <option value="">Choose&hellip;</option>
            ${boot.items.map((i) => `<option value="${i.id}">${UI.esc(i.name)}</option>`).join("")}
          </select>
        </label>
        <div id="bm-preview"></div>`;
      UI.modal({
        title: `Replace item on ${ticketIds.length} tickets`,
        body,
        wide: true,
        actions: [
          {
            label: "Preview",
            onClick: async () => {
              const from = Number(body.querySelector("#bm-from").value);
              const to = Number(body.querySelector("#bm-to").value);
              if (!from || !to) { UI.toast("Choose both items"); return; }
              const result = await Api.post("/api/bulk/replace", {
                ticket_ids: ticketIds, from_item_id: from, to_item_id: to, dry_run: true,
              });
              body.querySelector("#bm-preview").innerHTML = `
                <div class="summary-box">Would change <b>${result.tickets}</b> tickets (${result.swaps} swap${result.swaps === 1 ? "" : "s"}).</div>
                ${result.conflicts && result.conflicts.length ? `
                <div class="conflict-box">
                  <div class="conflict-title">&#9888; Conflicts if applied</div>
                  <ul>${result.conflicts.map((c) => `<li>${UI.esc(c.ticket)} &mdash; ${UI.esc(c.resident)}: ${UI.esc(c.reason)}</li>`).join("")}</ul>
                </div>` : ""}`;
              replaceConflicts = (result.conflicts || []).length;
            },
          },
          {
            label: "Apply",
            kind: "primary",
            onClick: async () => {
              const from = Number(body.querySelector("#bm-from").value);
              const to = Number(body.querySelector("#bm-to").value);
              if (!from || !to) { UI.toast("Choose both items"); return; }
              UI.closeModal();
              await this.runBulk(container, () => Api.post("/api/bulk/replace", {
                ticket_ids: ticketIds, from_item_id: from, to_item_id: to, force: replaceConflicts > 0,
              }));
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    }

    if (mode === "status") {
      body.innerHTML = `
        <p>Set status for <b>${ticketIds.length}</b> tickets:</p>
        ${boot.statuses.map((st) => `
          <label class="field" style="margin:6px 0">
            <input type="radio" name="bm-status" value="${st.value}" ${st.value === "ready" ? "checked" : ""}> ${UI.esc(st.label)}
          </label>`).join("")}`;
      UI.modal({
        title: `Set status on ${ticketIds.length} tickets`,
        body,
        actions: [
          {
            label: "Apply",
            kind: "primary",
            onClick: async () => {
              const status = body.querySelector("input[name=bm-status]:checked").value;
              UI.closeModal();
              await this.runBulk(container, () => Api.post("/api/bulk/status", {
                ticket_ids: ticketIds, status,
              }));
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    }

    if (mode === "note") {
      body.innerHTML = `
        <p>Add the same note to <b>${ticketIds.length}</b> tickets:</p>
        <label class="field">Note
          <textarea id="bm-note"></textarea>
        </label>
        <label class="field"><input type="radio" name="bm-mode" value="append" checked> Add to existing notes</label>
        <label class="field"><input type="radio" name="bm-mode" value="set"> Replace existing notes</label>`;
      UI.modal({
        title: `Add note to ${ticketIds.length} tickets`,
        body,
        actions: [
          {
            label: "Apply",
            kind: "primary",
            onClick: async () => {
              const note = body.querySelector("#bm-note").value.trim();
              if (!note) { UI.toast("Type a note first"); return; }
              const mode2 = body.querySelector("input[name=bm-mode]:checked").value;
              UI.closeModal();
              await this.runBulk(container, () => Api.post("/api/bulk/note", {
                ticket_ids: ticketIds, note, mode: mode2,
              }));
            },
          },
          { label: "Cancel", onClick: () => UI.closeModal() },
        ],
      });
    }
  },

  async runBulk(container, fn) {
    try {
      const result = await fn();
      if (result.conflicts && result.conflicts.length) {
        UI.modal({
          title: "Some tickets were skipped",
          body: `
            <div class="conflict-box">
              <div class="conflict-title">&#9888; ${result.conflicts.length} allergy/diet conflict${result.conflicts.length === 1 ? "" : "s"} skipped</div>
              <ul>${result.conflicts.map((c) => `<li>${UI.esc(c.ticket)} &mdash; ${UI.esc(c.resident)}: ${UI.esc(c.reason)}</li>`).join("")}</ul>
            </div>`,
          actions: [{ label: "Close", kind: "primary", onClick: () => UI.closeModal() }],
        });
      } else {
        UI.toast("Done", "success");
      }
      s_selectedRefresh(container);
    } catch (err) {
      UI.toast(err.message, "error");
    }
  },

  // ------------------------------------------------------------ generate
  generateModal(container) {
    const boot = this.boot;
    const s = this.state;
    const body = document.createElement("div");
    body.innerHTML = `
      <label class="field">Date
        <input type="date" id="gen-date" value="${s.filters.date}">
      </label>
      <label class="field">Meals
        <div class="btn-row">
          ${boot.meals.map((m) => `
            <label style="display:flex;gap:6px;align-items:center;font-weight:400">
              <input type="checkbox" name="gen-meal" value="${m.value}" ${m.value !== "snack" ? "checked" : ""}> ${UI.esc(m.label)}
            </label>`).join("")}
        </div>
      </label>
      <label class="field">Buildings
        <div class="btn-row">
          ${boot.buildings.length ? boot.buildings.map((b) => `
            <label style="display:flex;gap:6px;align-items:center;font-weight:400">
              <input type="checkbox" name="gen-building" value="${b.id}" checked> ${UI.esc(b.name)}
            </label>`).join("") : `<span class="muted">No buildings yet - add them in Settings first.</span>`}
        </div>
      </label>
      <div id="gen-preview"></div>`;
    UI.modal({
      title: "Generate tickets",
      body,
      actions: [
        {
          label: "Preview",
          onClick: async () => {
            const { date, meals, buildingIds } = readGen();
            const result = await Api.post("/api/tickets/generate", { date, meals, building_ids: buildingIds });
            body.querySelector("#gen-preview").innerHTML = `
              <div class="summary-box">${result.created} new tickets would be created; ${result.skipped} already exist.</div>`;
          },
        },
        {
          label: "Generate",
          kind: "primary",
          onClick: async () => {
            const { date, meals, buildingIds } = readGen();
            UI.closeModal();
            try {
              const result = await Api.post("/api/tickets/generate", { date, meals, building_ids: buildingIds });
              UI.toast(`Created ${result.created} tickets (${result.skipped} already existed)`, "success");
              await this.refresh(container);
            } catch (err) {
              UI.toast(err.message, "error");
            }
          },
        },
        { label: "Cancel", onClick: () => UI.closeModal() },
      ],
    });

    function readGen() {
      return {
        date: body.querySelector("#gen-date").value || UI.todayIso(),
        meals: [...body.querySelectorAll("input[name=gen-meal]:checked")].map((i) => i.value),
        buildingIds: [...body.querySelectorAll("input[name=gen-building]:checked")].map((i) => Number(i.value)),
      };
    }
  },
};

async function s_selectedRefresh(container) {
  await TicketsView.refresh(container);
}
