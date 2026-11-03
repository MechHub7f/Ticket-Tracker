/* Login + first-run setup view. */

const LoginView = {
  async render(container) {
    const status = await Api.get("/api/auth/status");
    if (status.user) {
      App.showApp();
      return;
    }
    const setup = status.setup_required;
    container.innerHTML = `
      <div class="login-wrap">
        <div class="login-card">
          <div class="logo-row">
            <div class="logo">🍽</div>
            <h1>Ticket Tracker</h1>
            <p class="sub">Meal tickets for ${setup ? "your facility" : "senior care"}</p>
          </div>
          ${setup ? `
          <form id="setup-form">
            <p><b>Welcome!</b> Create the first administrator account.</p>
            <label class="field">Your name
              <input type="text" id="su-name" autocomplete="name" required>
            </label>
            <label class="field">Username
              <input type="text" id="su-user" autocomplete="username" required>
            </label>
            <label class="field">Password
              <input type="password" id="su-pass" autocomplete="new-password" required>
              <span class="hint">At least 8 characters</span>
            </label>
            <button class="btn primary" type="submit" style="width:100%">Create account &amp; sign in</button>
          </form>` : `
          <form id="login-form">
            <label class="field">Username
              <input type="text" id="li-user" autocomplete="username" required>
            </label>
            <label class="field">Password
              <input type="password" id="li-pass" autocomplete="current-password" required>
            </label>
            <button class="btn primary" type="submit" style="width:100%">Sign in</button>
          </form>`}
        </div>
      </div>`;

    const form = container.querySelector(setup ? "#setup-form" : "#login-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        if (setup) {
          await Api.post("/api/auth/setup", {
            display_name: container.querySelector("#su-name").value.trim(),
            username: container.querySelector("#su-user").value.trim(),
            password: container.querySelector("#su-pass").value,
          });
        } else {
          await Api.post("/api/auth/login", {
            username: container.querySelector("#li-user").value.trim(),
            password: container.querySelector("#li-pass").value,
          });
        }
        await App.boot();
      } catch (err) {
        UI.toast(err.message, "error");
        button.disabled = false;
      }
    });
    (container.querySelector(setup ? "#su-name" : "#li-user") || {}).focus?.();
  },
};
