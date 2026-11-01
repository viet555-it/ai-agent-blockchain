import { dashboardApi } from '../api.js';
import { getLanguage, t } from '../i18n.js';

export function createChatController(state, elements, {
  appendMessage, showTypingIndicator, removeTypingIndicator, renderCitation,
  renderTimeline, openApprovalModal, renderWalletGate,
}, client = dashboardApi) {
  async function handleSendMessage(query) {
    if (!query || !query.trim() || state.isProcessing) return;
    const wallet = state.walletController;
    const generation = wallet?.generation;
    const conversation = wallet?.conversation;
    const epoch = state.historyView?.epoch;
    const current = () => !state.walletMode || (wallet.current(generation) && wallet.conversation === conversation && state.historyView.epoch === epoch);

    // Only block if viewing an archived/read-only conversation from a different deployment
    if (state.walletMode && wallet?.ready && conversation && state.historyView?.readOnly) {
      appendMessage('agent', t('wallet.loginRequired'));
      return;
    }

    const isGuestTurn = state.walletMode && (!wallet?.ready || !conversation);

    state.isProcessing = true;
    elements.btnSendMessage.disabled = true;
    elements.chatInput.value = '';

    // Append user message
    appendMessage('user', query);
    showTypingIndicator();

    try {
      let data;
      const activeLang = getLanguage();
      if (state.walletMode && !isGuestTurn) {
        const context = wallet.context;
        const requestId = crypto.randomUUID();
        const result = await client.turn(conversation, {
          query,
          context_id: context.id,
          generation: context.generation,
          client_request_id: requestId,
          language: activeLang,
        });
        if (!current()) return;
        data = result.response;
        if (!data) throw new Error(t('wallet.turnStatus', { status: result.status }));
      } else {
        data = await client.chat({
          query,
          wallet_address: state.wallet ? state.wallet.address : null,
          session_id: state.sessionId,
          language: activeLang,
        });
      }
      if (!current()) return;
      removeTypingIndicator();

      appendMessage('agent', data.reply, renderCitation(data));

      // Update Activity Timeline with sorted steps & normalized sequence numbering
      renderTimeline(data.timeline);

      // If approval is required, trigger approval modal
      if (data.requires_approval && data.guardrail_result && data.guardrail_result.pending_approval) {
        openApprovalModal(data.guardrail_result.pending_approval, data.guardrail_result);
      }

    } catch (err) {
      if (!current()) return;
      if (state.walletMode && err.status === 401) wallet.invalidate('signIn');
      removeTypingIndicator();
      appendMessage('agent', `❌ An error occurred: ${err.message}`);
      console.error('Chat error:', err);
    } finally {
      if (!current()) return;
      state.isProcessing = false;
      elements.btnSendMessage.disabled = false;
      elements.chatInput.focus();
      renderWalletGate();
    }
  }

  return { handleSendMessage };
}
