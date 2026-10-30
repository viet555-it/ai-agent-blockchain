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
    else if (wallet.ready) { message = state.historyLoading ? 'loadingChat' : state.historyView?.readOnly ? 'oldChat' : 'gateNewChat'; action = 'newChat'; }
    document.getElementById('wallet-chat-guidance').textContent = t(`wallet.${message}`, { chain: wallet.expectedChain });
    const button = document.getElementById('wallet-chat-action');
    button.textContent = t(`wallet.${action}`);
    button.disabled = busy;
    elements.chatInput.disabled = blocked || state.isProcessing;
    elements.btnSendMessage.disabled = blocked || state.isProcessing;
    elements.promptChips.querySelectorAll('button').forEach(button => { button.disabled = blocked || state.isProcessing; });
    for (const id of ['history-new', 'history-rename', 'history-archive', 'conversation-list']) {
      document.getElementById(id).disabled = !wallet.ready || state.historyLoading;
    }
    const controls = document.getElementById('wallet-controls');
    const agentReady = wallet.ready && wallet.conversation && !state.historyLoading && !state.historyView?.readOnly;
    controls.dataset.ready = String(Boolean(agentReady));
    if (wallet.ready) document.getElementById('wallet-status').textContent = t(`wallet.${state.historyLoading ? 'loadingChat' : agentReady ? 'ready' : 'gateNewChat'}`);
  }


  return { renderWalletGate };
}
