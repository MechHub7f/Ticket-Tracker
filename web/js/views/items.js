/* Items view - the meal item library with tags (gluten-free, low sodium...). */

const ItemsView = {
  state: null,

  defaults() {
    return { q: "", category: "", items: [] };
  },

  async render(container) {
    if (!this.state) this.state = this.defaults();
    const s = this.state;

    container.innerHTML = `
      <div class="topbar">
        <h1>Meal items</h1>
        <div class="actions">
          <button class="btn primary" id="btn-add">&#10133; Add item</button>
        </div>
      </div>
      <div class="filters">
        <label class="field search">Search
          <input type="text" id="i-q" placeholder="Item name or tag&hellip;">
        </label>
        <label class="field">Category
          <input type="text" id="i-cat" list="cat-list" placeholder="All categories">
          <datalist id="cat-list"></datalist>
        </label>
      </div>
      <div class="card table-wrap">
        <table>
          <thead><tr><th>Item</th><th>Category</th><th>Tags</th><th></th></tr></thead>
          <tbody id="i-rows"></tbody>
        </table>
      </div>`;

    const f = (id) => container.querySelector(id);
    f("#i-q").value = s.q;
    f("#i-cat").value = s.category;

    let timer = null;
    f("#i-q").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { s.q = f("#i-q").value; this.refresh(); }, 250);
    });
    f("#i-cat").addEventListener("change", () => { s.category = f("#i-cat").value.trim(); this.refresh(); });
    f("#btn-add").addEventListener("click", () => this.editModal(null));

    await this.refresh();
  },

  async refresh() {
    const s = this.state;
    const params = new URLSearchParams();
    if (s.q) params.set("q", s.q);
    if (s.category) params.set("category", s.category);
    try {
      const data = await Api.get(`/api/items?${params}`);
      s.items = data.items;
      const cats = [...new Set(s.items.map((i) => i.category).filter(Boolean))];
      const list = document.getElementById("cat-list");
      if (list) list.innerHTML = cats.map((c) => `<option value="${UI.esc(c)}">`).join("");
      this.paint();
    } catch (err) {
      UI.toast(err.message, "error");
    }
  },

  paint() {
    const rows = document.getElementById("i-rows");
    const s = this.state;
    if (!s.items.length) {
      rows.innerHTML = `<tr><td colspan="4">${UI.empty("No items yet. Add the meals and drinks your kitchen serves.", "&#127869;")}</td></tr>`;
      return;
    }
    rows.innerHTML = s.items.map((i) => `
      <tr>
        <td><b>${UI.esc(i.name)}</b></td>
        <td>${UI.esc(i.category || "")}</td>
        <td>${UI.chips(String(i.tags || "").split(/[,;]/).map((x) => x.trim()).filter(Boolean), "diet")}</td>
        <td class="actions">
          <button class="btn small" data-edit="${i.id}">Edit</button>
          <button class="btn small danger" data-del="${i.id}">Delete</button>
        </td>
      </tr>`).join("");

    rows.querySelectorAll("[data-edit]").forEach((btn) =>
      btn.addEventListener("click", () => this.editModal(s.items.find((i) => i.id === Number(btn.dataset.edit)))));
    rows.querySelectorAll("[data-del]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        if (!UI.confirm("Delete this item? Past tickets that used it keep a record of it.")) return;
        try {
          await Api.del(`/api/items/${btn.dataset.del}`);
          UI.toast("Item deleted", "success");
          this.refresh();
        } catch (err) { UI.toast(err.message, "error"); }
      }));
  },

  editModal(item) {
    const isNew = !item;
    const i = item || { name: "", category: "", tags: "" };
    const body = document.createElement("div");
    body.innerHTML = `
      <label class="field">Item name
        <input type="text" id="ei-name" value="${UI.esc(i.name)}" autocomplete="off">
      </label>
      <label class="field">Category <span class="hint">e.g. Entree, Starch, Vegetable, Beverage, Dessert</span>
        <input type="text" id="ei-cat" value="${UI.esc(i.category || "")}" list="ei-cats" autocomplete="off">
        <datalist id="ei-cats"></datalist>
      </label>
      <label class="field">Tags <span class="hint">Comma separated: gluten-free, low sodium, diabetic, contains nuts&hellip;</span>
        <input type="text" id="ei-tags" value="${UI.esc(i.tags || "")}" autocomplete="off">
      </label>`;

    UI.modal({
      title: isNew ? "Add meal item" : `Edit ${item.name}`,
      body,
      actions: [
        {
          label: "Save",
          kind: "primary",
          onClick: async () => {
            const data = {
              name: body.querySelector("#ei-name").value.trim(),
              category: body.querySelector("#ei-cat").value.trim(),
              tags: body.querySelector("#ei-tags").value.trim(),
            };
            if (!data.name) { UI.toast("Name is required", "error"); return; }
            try {
              if (isNew) await Api.post("/api/items", data);
              else await Api.patch(`/api/items/${item.id}`, data);
              UI.closeModal();
              UI.toast(isNew ? "Item added" : "Saved", "success");
              await App.bootData(true);
              this.refresh();
            } catch (err) { UI.toast(err.message, "error"); }
          },
        },
        { label: "Cancel", onClick: () => UI.closeModal() },
      ],
    });
    body.querySelector("#ei-cats").innerHTML = ["Entree", "Starch", "Vegetable", "Soup", "Salad", "Beverage", "Dessert", "Snack"]
      .map((c) => `<option value="${c}">`).join("");
  },
};
