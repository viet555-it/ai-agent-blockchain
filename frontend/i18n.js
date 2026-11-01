/**
 * Internationalization (i18n) Engine
 * Supports Auto, Vietnamese (vi), and English (en) with reactive updates.
 */
// The API serves native browser modules directly, without a Vite build.
const translations = { en: {}, vi: {} };
const STORAGE_KEY = 'ati_language';
const DEFAULT_LANG = 'en';
const SUPPORTED_LANGS = new Set(['auto', 'en', 'vi']);

let currentLang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;
if (!SUPPORTED_LANGS.has(currentLang)) {
  currentLang = DEFAULT_LANG;
}

const listeners = new Set();

function getEffectiveLang() {
  if (currentLang === 'auto') {
    return (typeof navigator !== 'undefined' && navigator.language && navigator.language.startsWith('vi'))
      ? 'vi'
      : 'en';
  }
  return currentLang;
}

export async function initializeI18n() {
  await Promise.all(['en', 'vi'].map(async lang => {
    const response = await fetch(new URL(`./locales/${lang}.json`, import.meta.url));
    if (!response.ok) throw new Error(`Unable to load locale ${lang}`);
    translations[lang] = await response.json();
  }));
  document.documentElement.lang = getEffectiveLang();
}

/**
 * Get current configured language code ('auto' | 'en' | 'vi')
 */
export function getLanguage() {
  return currentLang;
}

/**
 * Set current active language code, save to localStorage, and notify listeners
 */
export function setLanguage(lang) {
  if (!SUPPORTED_LANGS.has(lang)) return;
  currentLang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch (e) {
    console.warn('Unable to persist language in localStorage:', e);
  }
  document.documentElement.lang = getEffectiveLang();
  notifyListeners(lang);
}

/**
 * Subscribe to language changes
 */
export function onLanguageChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notifyListeners(lang) {
  listeners.forEach(fn => {
    try {
      fn(lang);
    } catch (e) {
      console.error('Error in i18n listener:', e);
    }
  });
}

/**
 * Translate a key path (e.g. 'network.title' or 'steps.Request received')
 * Supports variable interpolation: {fee}, {current}, etc.
 */
export function t(key, params = {}, fallback = key) {
  const active = getEffectiveLang();
  const langDict = translations[active] || translations[DEFAULT_LANG];
  let val = resolveKey(langDict, key);

  // Fallback to English dictionary if key not found in current language
  if (val === undefined && active !== DEFAULT_LANG) {
    val = resolveKey(translations[DEFAULT_LANG], key);
  }

  // Fallback to key itself if not found
  if (val === undefined) {
    return fallback;
  }

  if (typeof val === 'string' && Object.keys(params).length > 0) {
    return val.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? params[k] : `{${k}}`));
  }

  return val;
}

function resolveKey(obj, path) {
  if (!obj || !path) return undefined;

  // Try direct property first (useful for keys containing spaces or dots like step names)
  if (obj[path] !== undefined) return obj[path];

  // Try dot-notation path
  const parts = path.split('.');
  let current = obj;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part];
    } else {
      return undefined;
    }
  }
  return current;
}

/**
 * Walk the DOM and translate elements with data-i18n attributes.
 */
export function updateDomTranslations(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });

  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key) el.setAttribute('placeholder', t(key));
  });

  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key) el.setAttribute('title', t(key));
  });
}
