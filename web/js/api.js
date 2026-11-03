/* API helper - all requests go through here. */

const Api = {
  async call(method, path, body) {
    const options = {
      method,
      headers: {},
      credentials: "same-origin",
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (err) {
      throw new Error("Cannot reach the server. Is it running?");
    }
    let data = null;
    const text = await response.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = { error: text }; }
    }
    if (!response.ok) {
      const message = (data && data.error) || `Request failed (${response.status})`;
      if (response.status === 401 && window.App && App.authenticated()) {
        App.onSessionExpired();
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data;
  },

  get(path) { return this.call("GET", path); },
  post(path, body) { return this.call("POST", path, body || {}); },
  patch(path, body) { return this.call("PATCH", path, body || {}); },
  del(path) { return this.call("DELETE", path); },
};
