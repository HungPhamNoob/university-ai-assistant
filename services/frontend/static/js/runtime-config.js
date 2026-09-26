/* services/frontend/static/js/runtime-config.js
 * Runtime configuration. Placeholder content:
 *   - nginx/entrypoint.sh rewrites this file at container start (heredoc shell
 *     expansion of FRONTEND_API_BASE_URL), so the values below are the LOCAL-DEV
 *     defaults.
 *
 * Mode resolution (see js/api.js):
 *   - gatewayBaseUrl non-empty  -> gateway mode (browser calls Kong directly, Bearer JWT).
 *   - proxyGateway === true     -> proxy mode (served behind nginx; empty base = same-origin
 *                                  relative paths proxied to the Kong gateway).
 *   - otherwise                 -> direct mode (local dev, browser calls the three
 *                                  microservices on localhost directly).
 */
window.API_BASE_URL = "";
window.APP_CONFIG = {
  gatewayBaseUrl: "",
  proxyGateway: false,
  direct: {
    agent: "http://localhost:8000",
    identity: "http://localhost:8001",
    conversation: "http://localhost:8004",
    rag: "http://localhost:8002",
  },
};