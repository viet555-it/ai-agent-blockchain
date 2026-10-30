import { t, getLanguage, setLanguage, updateDomTranslations } from '../i18n.js';

export function createLanguageView(state, elements, { updateNetworkLabels, renderTimeline }) {
  function updateLanguageUI(lang) {
    state.language = lang;
    if (lang === 'vi') {
      elements.langOptVi.classList.add('active');
      elements.langOptEn.classList.remove('active');
    } else {
      elements.langOptEn.classList.add('active');
      elements.langOptVi.classList.remove('active');
    }

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
    const nextLang = getLanguage() === 'en' ? 'vi' : 'en';
    setLanguage(nextLang);
  }


  return { updateLanguageUI, toggleLanguage };
}
