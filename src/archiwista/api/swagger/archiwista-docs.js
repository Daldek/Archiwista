// Swagger UI of the local Archiwista API (/api/docs). The page runs under the
// server's CSP, so it has no inline script: this file starts the UI on the
// OpenAPI document and adds the session's CSRF token to every request (reads
// too). The token comes from this tab's sessionStorage (the interface keeps
// it there) or, in a new tab, from an open tab of the interface.
window.addEventListener("load", () => {
  const key = "archiwista_csrf";
  const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("archiwista-session") : null;
  const ask = () =>
    new Promise((resolve) => {
      if (channel === null) return resolve(null);
      const answer = ({ data }) => {
        if (data && data.type === "token" && typeof data.token === "string") done(data.token);
      };
      const done = (token) => {
        clearTimeout(timer);
        channel.removeEventListener("message", answer);
        resolve(token);
      };
      const timer = setTimeout(() => done(null), 300);
      channel.addEventListener("message", answer);
      channel.postMessage({ type: "ask" });
    });
  const start = (token) => {
    if (token !== null) sessionStorage.setItem(key, token);
    window.ui = window.SwaggerUIBundle({
      url: "/api/v1/openapi.json",
      dom_id: "#swagger-ui",
      deepLinking: true,
      requestInterceptor: (request) => {
        const current = sessionStorage.getItem(key);
        if (current !== null) request.headers["X-Archiwista-CSRF"] = current;
        return request;
      },
    });
  };
  const kept = sessionStorage.getItem(key);
  if (kept !== null) start(kept);
  else ask().then(start);
});
