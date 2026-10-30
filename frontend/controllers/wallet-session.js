import { WalletController } from '../wallet.js';
import { HistoryView } from '../history.js';
import { t, onLanguageChange } from '../i18n.js';
import { shortenAddress } from '../ui/format.js';

export function createWalletSession(state, elements, { appendMessage, renderTimeline, openApprovalModal, closeApprovalModal, loadWalletInfo, renderWalletGate }) {
  function clearWalletView() {
    state.followLatest = true;
    elements.chatHistory.replaceChildren();
    closeApprovalModal();
    state.isProcessing = false;
    state.lastTimelineSteps = null;
    elements.timelineList.replaceChildren();
    elements.timelineList.style.display = 'none';
    elements.timelineEmptyState.style.display = '';
    elements.timelineStepCount.textContent = '0 / 9';
    elements.btnSendMessage.disabled = state.walletMode && (!state.walletController.ready || state.historyView?.readOnly);
    renderWalletGate();
  }

  async function initializeWalletMode(health) {
    state.walletMode = health.wallet_history_enabled;
    if (!state.walletMode) return;
    const wallet = new WalletController(health.chain_id);
    state.walletController = wallet;
    const controls = document.getElementById('wallet-controls');
    controls.hidden = false;
    document.getElementById('wallet-chip').hidden = true;
    document.getElementById('wallet-history').hidden = false;
    const reportError = error => {
      const messages = { 4001: 'rejectedRequest', '-32002': 'pendingRequest', 4902: 'addNetworkFirst', ORIGIN: 'wrongOrigin', AUTH_REQUIRED: 'gateSignIn', DEPLOYMENT_UNAVAILABLE: health.chain_id === 31337 ? 'deploymentUnavailable' : undefined };
      const message = messages[error.code];
      renderWalletGate();
      controls.dataset.ready = 'false';
      document.getElementById('wallet-status').textContent = message ? t(`wallet.${message}`) : error.message;
    };
    const history = new HistoryView(wallet, { clear: clearWalletView, append: appendMessage,
      timeline: renderTimeline, approval: openApprovalModal, error: reportError });
    state.historyView = history;
    let generation = -1;
    let contextId = null;
    const providerSelect = document.getElementById('wallet-provider');
    const providers = () => {
      const selected = providerSelect.value;
      providerSelect.replaceChildren();
      for (const [id, item] of wallet.providers) {
        const option = document.createElement('option');
        option.value = id;
        option.textContent = item.name;
        providerSelect.append(option);
      }
      if (wallet.providers.has(selected)) providerSelect.value = selected;
      providerSelect.hidden = wallet.ready || wallet.providers.size <= 1;
      renderWalletGate();
    };
    const update = () => {
      if (generation !== wallet.generation) {
        generation = wallet.generation;
        document.getElementById('wallet-menu').open = false;
        state.historyLoading = false;
        contextId = null;
        history.clear();
        state.wallet = null;
        elements.headerWalletAddress.textContent = wallet.address ? shortenAddress(wallet.address) : '--';
        elements.valNativeBalance.textContent = '--';
        elements.valTokenBalance.textContent = '--';
      }
      elements.headerWalletAddress.textContent = wallet.address ? shortenAddress(wallet.address) : '--';
      document.getElementById('wallet-status').textContent = t(`wallet.${wallet.status}`);
      document.getElementById('wallet-connect').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
      document.getElementById('wallet-switch').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
      document.getElementById('wallet-connect').hidden = wallet.ready;
      document.getElementById('wallet-connect').textContent = t(`wallet.${wallet.connecting || wallet.authenticating ? 'confirmInWallet' : 'connectSignIn'}`);
      document.getElementById('wallet-menu').hidden = !wallet.ready;
      document.getElementById('wallet-menu-address').textContent = shortenAddress(wallet.address);
      document.getElementById('wallet-switch').hidden = !wallet.address;
      document.getElementById('wallet-disconnect').hidden = !wallet.address;
      document.getElementById('wallet-provider').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
      document.getElementById('wallet-provider').hidden = wallet.ready || wallet.providers.size <= 1;
      elements.btnSendMessage.disabled = !wallet.ready || state.isProcessing || history.readOnly;
      if (wallet.ready && contextId !== wallet.context.id) {
        contextId = wallet.context.id;
        const expectedGeneration = wallet.generation;
        state.historyLoading = true;
        loadWalletInfo();
        history.initialize().catch(error => { if (wallet.current(expectedGeneration)) reportError(error); }).finally(() => {
          if (wallet.current(expectedGeneration)) { state.historyLoading = false; renderWalletGate(); }
        });
      }
      renderWalletGate();
    };
    wallet.addEventListener('change', update);
    wallet.addEventListener('error', event => reportError(event.detail));
    wallet.addEventListener('providers', providers);
    onLanguageChange(update);
    document.getElementById('wallet-connect').addEventListener('click', () => wallet.connectAndSignIn(providerSelect.value).catch(reportError));
    document.getElementById('wallet-switch').addEventListener('click', () => {
      document.getElementById('wallet-menu').open = false;
      wallet.connectAndSignIn(providerSelect.value, true).catch(reportError);
    });
    document.getElementById('wallet-disconnect').addEventListener('click', () => {
      document.getElementById('wallet-menu').open = false;
      wallet.disconnect().catch(reportError);
    });
    document.getElementById('wallet-copy').addEventListener('click', () => {
      if (wallet.address) navigator.clipboard.writeText(wallet.address).catch(reportError);
      document.getElementById('wallet-menu').open = false;
    });
    document.getElementById('wallet-chat-action').addEventListener('click', async () => {
      try {
        if (!wallet.providers.size) { wallet.surface.dispatchEvent(new Event('eip6963:requestProvider')); providers(); return; }
        if (!wallet.ready) await wallet.connectAndSignIn(providerSelect.value);
        else await history.create();
      } catch (error) { reportError(error); }
    });
    wallet.discover();
    providers();
    update();
    await wallet.restore();
    await wallet.retryReports();
  }


  return { clearWalletView, initializeWalletMode };
}
