// Override apiBase at deployment time when the API is not served from this origin.
// Same-origin is the safe default and requires no CORS relaxation.
window.OBSERVABILITY_DASHBOARD_CONFIG = Object.freeze({ apiBase: "" });
