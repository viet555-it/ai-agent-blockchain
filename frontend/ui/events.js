import { icons } from '../icons.js';
import { t, onLanguageChange } from '../i18n.js';

export function bindDashboardEvents(state, elements, {
  toggleTheme, toggleLanguage, updateLanguageUI, handleSendMessage,
  loadNetworkStatus, loadWalletInfo, loadPolicies, submitApprovalAction, closeApprovalModal,
}) {
  // Theme Toggle
  elements.btnToggleTheme.addEventListener('click', toggleTheme);

  // Language Toggle
  elements.btnToggleLang.addEventListener('click', toggleLanguage);

  // Subscribe to i18n changes
  onLanguageChange((lang) => {
    updateLanguageUI(lang);
  });

  // Chat form submit
  elements.chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = elements.chatInput.value.trim();
    handleSendMessage(query);
  });

  // Prompt suggestions
  elements.promptChips.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) handleSendMessage(prompt);
    });
  });

  // Refresh assets
  elements.btnRefreshAssets.addEventListener('click', () => {
    elements.btnRefreshAssets.style.transform = 'rotate(180deg)';
    Promise.all([loadNetworkStatus(), loadWalletInfo(), loadPolicies()]).finally(() => {
      setTimeout(() => { elements.btnRefreshAssets.style.transform = 'none'; }, 300);
    });
  });

  // Copy header wallet
  elements.btnCopyHeaderWallet.addEventListener('click', () => {
    if (state.wallet && state.wallet.address) {
      navigator.clipboard.writeText(state.wallet.address);
      const original = elements.btnCopyHeaderWallet.innerHTML;
      elements.btnCopyHeaderWallet.innerHTML = icons.checkCircle;
      elements.btnCopyHeaderWallet.title = t('header.walletCopied');
      setTimeout(() => {
        elements.btnCopyHeaderWallet.innerHTML = original;
        elements.btnCopyHeaderWallet.title = t('header.copyWallet');
      }, 1500);
    }
  });

  // Modal actions
  elements.btnModalApprove.addEventListener('click', () => submitApprovalAction('APPROVE'));
  elements.btnModalReject.addEventListener('click', () => submitApprovalAction('REJECT'));

  // Close modal on escape key
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && elements.approvalModal.classList.contains('open')) {
      closeApprovalModal();
    }
  });
}
