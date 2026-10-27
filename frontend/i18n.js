/**
 * Internationalization (i18n) Engine
 * Supports Vietnamese (vi) and English (en) with reactive updates.
 */
import en from './locales/en.json';
import vi from './locales/vi.json';

const translations = { en, vi };
const STORAGE_KEY = 'ati_language';
const DEFAULT_LANG = 'en';

let currentLang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;
if (!translations[currentLang]) {
  currentLang = DEFAULT_LANG;
}

const listeners = new Set();

/**
 * Get current active language code ('en' | 'vi')
 */
export function getLanguage() {
  return currentLang;
}

/**
 * Set current active language code, save to localStorage, and notify listeners
 */
export function setLanguage(lang) {
  if (!translations[lang]) return;
  currentLang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch (e) {
    console.warn('Unable to persist language in localStorage:', e);
  }
  document.documentElement.lang = lang;
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
export function t(key, params = {}) {
  const langDict = translations[currentLang] || translations[DEFAULT_LANG];
  let val = resolveKey(langDict, key);

  // Fallback to English dictionary if key not found in current language
  if (val === undefined && currentLang !== DEFAULT_LANG) {
    val = resolveKey(translations[DEFAULT_LANG], key);
  }

  // Fallback to key itself if not found
  if (val === undefined) {
    return key;
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
 * Update all DOM elements with data-i18n attributes
 */
export function updateDomTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const translation = t(key);
    if (el.hasAttribute('data-i18n-html')) {
      el.innerHTML = translation;
    } else {
      el.textContent = translation;
    }
  });

  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.setAttribute('placeholder', t(key));
  });

  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    el.setAttribute('title', t(key));
  });
}

