import { icons } from '../icons.js';

export function createThemeView(state, elements) {
  function initIcons() {
    elements.appBrandIcon.innerHTML = icons.bot;
    elements.btnCopyHeaderWallet.innerHTML = icons.copy;
    elements.iconBlockchainPanel.innerHTML = icons.wallet;
    elements.btnRefreshAssets.innerHTML = icons.refresh;
    elements.iconExternalContract.innerHTML = icons.externalLink;
    elements.iconGuardrailBadge.innerHTML = icons.shield;
    elements.iconChatPanel.innerHTML = icons.bot;
    elements.iconSendBtn.innerHTML = icons.send;
    elements.iconActivityPanel.innerHTML = icons.activity;
    elements.iconEmptyTimeline.innerHTML = icons.layers;
    elements.iconModalShield.innerHTML = icons.shield;
    elements.iconModalCheck.innerHTML = icons.checkCircle;
    elements.iconModalApprove.innerHTML = icons.checkCircle;
    elements.iconLangBtn.innerHTML = icons.globe;
    updateThemeIcon();
  }

  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('ati_theme', theme);
    } catch (e) {
      console.warn('Unable to persist theme:', e);
    }
    updateThemeIcon();
  }

  function updateThemeIcon() {
    if (state.theme === 'light') {
      elements.iconThemeBtn.innerHTML = icons.moon;
      elements.themeLabelText.textContent = 'Light';
    } else {
      elements.iconThemeBtn.innerHTML = icons.sun;
      elements.themeLabelText.textContent = 'Dark';
    }
  }

  function toggleTheme() {
    const nextTheme = state.theme === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
  }


  return { initIcons, applyTheme, updateThemeIcon, toggleTheme };
}
