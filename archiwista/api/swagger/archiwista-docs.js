// Swagger UI of the local Archiwista API (/api/docs). The page runs under the
// server's CSP, so it has no inline script: this file starts the UI on the
// session's OpenAPI document and adds the session's CSRF token (the
// archiwista_csrf cookie) to every request that changes state.
window.addEventListener("load", () => {
  const csrfToken = () => {
    const found = document.cookie.match(/(?:^|;\s*)archiwista_csrf=([^;]*)/);
    return found ? decodeURIComponent(found[1]) : "";
  };
  window.ui = window.SwaggerUIBundle({
    url: "/api/v1/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    requestInterceptor: (request) => {
      const method = (request.method || "GET").toUpperCase();
      if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
        request.headers["X-Archiwista-CSRF"] = csrfToken();
      }
      return request;
    },
  });
});
