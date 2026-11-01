import { t, getLanguage, setLanguage, updateDomTranslations } from '../i18n.js';

export function createLanguageView(state, elements, { updateNetworkLabels, renderTimeline }) {
  function updateLanguageUI(lang) {
    state.language = lang;
    if (elements.langOptAuto) elements.langOptAuto.classList.toggle('active', lang === 'auto');
    if (elements.langOptVi) elements.langOptVi.classList.toggle('active', lang === 'vi');
    if (elements.langOptEn) elements.langOptEn.classList.toggle('active', lang === 'en');

    // Update all declarative elements in DOM
    updateDomTranslations();
    updateNetworkLabels();

    // Update dynamic prompt chip queries
    elements.promptChips.querySelectorAll('.prompt-chip').forEach(chip => {
      const key = chip.getAttribute('data-prompt-key');
      if (key) {
        chip.setAttribute('data-prompt', t(key));
      }
    });

    // Re-render base fee if present
    if (state.lastBaseFeeGwei !== null) {
      elements.valBaseFee.textContent = t('network.baseFee', { fee: state.lastBaseFeeGwei });
    }

    // Re-render timeline if steps exist
    if (state.lastTimelineSteps && state.lastTimelineSteps.length > 0) {
      renderTimeline(state.lastTimelineSteps);
    } else {
      elements.timelineStepCount.textContent = t('timeline.stepsCount', { current: 0, total: 9 });
    }

    // Update document title
    document.title = lang === 'vi'
      ? 'AI Agent với Công cụ Blockchain | Web3 Security & Guardrail Engine'
      : 'AI Agent with Blockchain Tools | Web3 Security & Guardrail Engine';
  }

  function toggleLanguage() {
    const cur = getLanguage();
    const nextLang = cur === 'en' ? 'vi' : cur === 'vi' ? 'auto' : 'en';
    setLanguage(nextLang);
  }

  return { updateLanguageUI, toggleLanguage };
}
