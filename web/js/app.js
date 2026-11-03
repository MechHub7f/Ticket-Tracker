/* App shell: session, routing, navigation. */

const App = {
  user: null,
  boot: null,
  currentView: null,
  viewContainer: null,

  views: {
    tickets: TicketsView,
    residents: ResidentsView,
    items: ItemsView,
    settings: SettingsView,
  },

  async bootData(force = false) {
    if (force || !this.boot) {
      this.boot = await Api.get("/api/bootstrap");
      if (this.boot.user) this.user = this.boot.user;
    }
    return this.boot;
  },

  authenticated() {
    return Boolean(this.user);
  },

  async start() {
    this.viewContainer = document.getElementById("app");
    try {
      const status = await Api.get("/api/auth/status");
      if (status.user) {
        this.user = status.user;
        await this.showApp();
      } else {
        this.renderLogin();
      }
    } catch (err) {
      this.viewContainer.innerHTML = `
        <div class="login-wrap"><div class="login-card">
          <h1>Ticket Tracker</h1>
          <p>${UI.esc(err.message)}</p>
          <button class="btn primary" onclick="location.reload()">Try again</button>
        </div></div>`;
    }
  },

  renderLogin() {
    document.title = "Sign in - Ticket Tracker";
    LoginView.render(this.viewContainer);
  },

  async showApp() {
    await this.bootData();
    document.title = "Ticket Tracker";
    this.viewContainer.innerHTML = `
      <div class="app-shell">
        <aside class="sidebar">
          <div class="brand"><div class="logo">🍽</div> Ticket Tracker</div>
          <nav id="nav"></nav>
          <div class="foot">
            <div class="who">${UI.esc(this.user.display_name || this.user.username)}</div>
            <div>${this.user.role === "admin" ? "Administrator" : "Staff"}</div>
            <button class="nav-btn" id="btn-logout" style="margin-top:10px">&#9099; Sign out</button>
          </div>
        </aside>
        <main class="main" id="view"></main>
      </div>`;
    document.getElementById("btn-logout").addEventListener("click", async () => {
      try { await Api.post("/api/auth/logout"); } catch {}
      this.user = null;
      this.boot = null;
      this.renderLogin();
    });
    this.route();
    window.addEventListener("hashchange", () => this.route());
  },

  route() {
    const main = document.getElementById("view");
    if (!main) return;
    const hash = (location.hash || "#/tickets").replace("#/", "").split("?")[0];
    const name = this.views[hash] ? hash : "tickets";
    this.currentView = this.views[name];
    document.querySelectorAll(".nav-btn[data-nav]").forEach((b) =>
      b.classList.toggle("active", b.dataset.nav === name));
    this.currentView.render(main);
  },

  onSessionExpired() {
    this.user = null;
    this.boot = null;
    UI.toast("Please sign in again");
    this.renderLogin();
  },

  paintNav() {
    const nav = document.getElementById("nav");
    if (!nav) return;
    const items = [
      ["tickets", "&#128203;", "Tickets"],
      ["residents", "&#128100;", "Residents"],
      ["items", "&#127869;", "Meal items"],
      ["settings", "&#9881;", "Settings"],
    ];
    nav.innerHTML = items.map(([id, icon, label]) =>
      `<button class="nav-btn" data-nav="${id}" onclick="location.hash='#/${id}'">
        <span class="icon">${icon}</span> ${label}
      </button>`).join("");
  },
};

// Patch showApp to draw the nav after the shell exists.
const _showApp = App.showApp.bind(App);
App.showApp = async function () {
  await _showApp();
  this.paintNav();
  this.route();
};

// Register service worker for the installable desktop app.
if ("serviceWorker" in navigator && location.protocol === "http:" || "serviceWorker" in navigator && location.protocol === "https:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

window.addEventListener("DOMContentLoaded", () => App.start());
