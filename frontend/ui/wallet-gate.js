import { t } from '../i18n.js';

export function createWalletGate(state, elements) {
  function renderWalletGate() {
    if (!state.walletMode) return;
    const wallet = state.walletController;
    const blocked = !wallet.ready || !wallet.conversation || state.historyView?.readOnly || state.historyLoading;
    const busy = wallet.connecting || wallet.authenticating || state.historyLoading;
    const gate = document.getElementById('wallet-chat-gate');
    gate.hidden = !blocked;
    let message = 'gateConnect', action = 'connectSignIn';
    if (!wallet.providers.size) { message = 'noProvider'; action = 'detectWallet'; }
    else if (wallet.status === 'wrongNetwork') { message = 'gateNetwork'; }
    else if (wallet.address && !wallet.ready) { message = 'gateSignIn'; }
    else if (wallet.ready) { message = state.historyLoading ? 'loadingChat' : state.historyView?.archivedReadOnly ? 'archivedChat' : state.historyView?.readOnly ? 'oldChat' : 'gateNewChat'; action = 'newChat'; }
    document.getElementById('wallet-chat-guidance').textContent = t(`wallet.${message}`, { chain: wallet.expectedChain });
    const button = document.getElementById('wallet-chat-action');
    button.textContent = t(`wallet.${action}`);
    button.disabled = busy;

    // Allow typing & guest chat questions even before connecting wallet
    const inputDisabled = Boolean(state.historyView?.readOnly || state.isProcessing || state.historyLoading);
    elements.chatInput.disabled = inputDisabled;
    elements.btnSendMessage.disabled = inputDisabled;
    elements.promptChips.querySelectorAll('button').forEach(button => { button.disabled = inputDisabled; });

    for (const id of ['history-new', 'history-archived-toggle', 'conversation-list']) {
      const el = document.getElementById(id);
      if (el) el.disabled = !wallet.ready || state.historyLoading;
    }
    document.querySelectorAll('#conversation-list button').forEach(button => {
      button.disabled = !wallet.ready || state.historyLoading;
    });
    const controls = document.getElementById('wallet-controls');
    const agentReady = wallet.ready && wallet.conversation && !state.historyLoading && !state.historyView?.readOnly;
    if (controls) controls.dataset.ready = String(Boolean(agentReady));
    if (wallet.ready) {
      const statusEl = document.getElementById('wallet-status');
      if (statusEl) statusEl.textContent = t(`wallet.${state.historyLoading ? 'loadingChat' : agentReady ? 'ready' : 'gateNewChat'}`);
    }
  }

  return { renderWalletGate };
}
