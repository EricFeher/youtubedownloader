// English is the source catalog. Both the UI and Python use the same text keys.
const DEFAULT_LANGUAGE = "en";
const catalogs = Object.fromEntries(await Promise.all(["en", "hu"].map(async (language) => {
  const response = await fetch(new URL(`locales/${language}.json`, import.meta.url));
  if (!response.ok) throw new Error(`Could not load ${language} translations: ${response.status}`);
  return [language, Object.freeze(await response.json())];
})));

export const TEXT = Object.freeze(Object.fromEntries(Object.keys(catalogs.en).map((key) => [key, key])));
let language = DEFAULT_LANGUAGE;
let pluralRules = new Intl.PluralRules(language);
const bindings = new WeakMap();

export function detectLanguage(locale) {
  const code = String(locale ?? "").split(/[-_]/)[0].toLowerCase();
  return Object.hasOwn(catalogs, code) ? code : DEFAULT_LANGUAGE;
}

export function t(source, params = {}) {
  if (source && typeof source === "object") {
    params = source.params ?? {};
    source = source.message;
    if (source && typeof source === "object") return t(source);
  }
  source = String(source ?? "");
  const key = source;
  let text = catalogs[language][key] ?? catalogs[DEFAULT_LANGUAGE][key] ?? source;
  if (typeof text === "object") text = text[pluralRules.select(params.count)] ?? text.other;
  // Substitute once: video titles and error details may themselves contain braces.
  return text.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(params, key)
    ? (params[key] && typeof params[key] === "object" ? t(params[key]) : String(params[key])) : match);
}

export function setText(node, source, params = {}) {
  bindings.set(node, { source, params });
  node.dataset.i18nMessage = "";
  node.textContent = t(source, params);
}

function translatePage() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  for (const attr of ["aria-label", "placeholder", "title"]) {
    document.querySelectorAll(`[data-i18n-${attr}]`).forEach((node) => {
      node.setAttribute(attr, t(node.getAttribute(`data-i18n-${attr}`)));
    });
  }
  document.querySelectorAll("[data-i18n-message]").forEach((node) => {
    const binding = bindings.get(node);
    if (binding) node.textContent = t(binding.source, binding.params);
  });
}

export function setLanguage(value) {
  language = detectLanguage(value);
  pluralRules = new Intl.PluralRules(language);
  translatePage();
  return language;
}

window.i18n = { TEXT, t, setText, setLanguage, detectLanguage,
  get language() { return language; }, get locale() { return language === "hu" ? "hu-HU" : "en-GB"; } };
