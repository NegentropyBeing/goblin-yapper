// Text for the panel and the overlay: one JSON catalog per language (web/i18n/<lang>.json).
// English is the reference; a key missing from the chosen language falls back to English.
//   markup:  data-i18n="key"  data-i18n-title="key"  data-i18n-placeholder="key"  data-i18n-confirm="key"
//   script:  t("key", { name: "value" })   (third argument true: the text is HTML, so the values are escaped)
(function () {
  const LANGS = ["en", "pt-BR"];
  let lang = "en", cat = {}, ref = {};

  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // The operator's stored choice wins; without one, follow the system: Portuguese -> pt-BR, anything else -> en.
  function resolveLanguage(stored) {
    if (LANGS.includes(stored)) return stored;
    return String(navigator.language || "en").toLowerCase().startsWith("pt") ? "pt-BR" : "en";
  }

  async function fetchCatalog(l) {
    try { return await (await fetch(`/web/i18n/${l}.json`)).json(); } catch { return {}; }
  }

  async function load(l) {
    lang = LANGS.includes(l) ? l : "en";
    ref = await fetchCatalog("en");
    cat = lang === "en" ? ref : await fetchCatalog(lang);
    document.documentElement.lang = lang;
  }

  function t(key, params, html) {
    let text = cat[key] ?? ref[key] ?? key;
    if (params) text = text.replace(/\{(\w+)\}/g, (m, k) => k in params ? (html ? esc(params[k]) : String(params[k])) : m);
    return text;
  }

  // A message from the server: { key, params }
  const fromServer = (msg) => t(msg.key, msg.params);

  function apply(root = document) {
    for (const el of root.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
    for (const attr of ["title", "placeholder"])
      for (const el of root.querySelectorAll(`[data-i18n-${attr}]`)) el.setAttribute(attr, t(el.getAttribute(`data-i18n-${attr}`)));
    for (const el of root.querySelectorAll("[data-i18n-confirm]")) el.dataset.confirm = t(el.dataset.i18nConfirm);
  }

  window.t = t;
  window.i18n = { LANGS, resolveLanguage, load, apply, fromServer, get lang() { return lang; } };
})();
