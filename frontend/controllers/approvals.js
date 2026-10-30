import { dashboardApi } from '../api.js';
import { t } from '../i18n.js';

export function createApprovalController(state, elements, {
  appendMessage, closeApprovalModal, loadWalletInfo, loadNetworkStatus,
}, client = dashboardApi) {
  async function submitApprovalAction(action) {
    if (!state.pendingApproval) return;
    if (state.walletMode) {
      const wallet = state.walletController;
      const generation = wallet.generation;
      elements.btnModalApprove.disabled = true;
      elements.btnModalReject.disabled = true;
      try {
        const result = await wallet.submit(state.pendingApproval, action);
        if (!wallet.current(generation)) return;
        closeApprovalModal();
        appendMessage('agent', action === 'REJECT' ? t('modal.rejectedMsg') : t('wallet.sent', { hash: result.tx_hash }));
        await state.historyView.refreshTransactions();
        await loadWalletInfo();
      } catch (error) {
        if (!wallet.current(generation)) return;
        closeApprovalModal();
        appendMessage('agent', error.message);
        await state.historyView.refreshTransactions().catch(() => {});
      }
      return;
    }

    const approvalId = state.pendingApproval.approval_id;
    const params = state.activeApprovalParameters;

    elements.btnModalApprove.disabled = true;
    elements.btnModalReject.disabled = true;
    elements.btnModalApprove.querySelector('span:first-child').textContent = t('modal.processing');

    try {
      let data = await client.reviewApproval({
        approval_id: approvalId,
        action,
        parameters: params,
        session_id: state.sessionId,
        reviewer_comment: action === 'APPROVE' ? 'Approved by user via dashboard' : 'Rejected by user',
      });

      // Receipt polling never resubmits APPROVE or broadcasts another transaction.
      for (let attempt = 0; action === 'APPROVE' && data.status === 'PENDING' && attempt < 8; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        try {
          data = await client.approvalStatus(approvalId, state.sessionId);
        } catch {
          break;
        }
      }

      closeApprovalModal();

      if (action === 'APPROVE') {
        const explorerLink = data.explorer_url
          ? `<div style="margin-top: 0.5rem;"><a href="${data.explorer_url}" target="_blank" rel="noopener noreferrer" style="color: var(--primary); text-decoration: underline; font-weight: 600;">${t('modal.viewTx')}</a></div>`
          : '';

        const descriptions = {
          CONFIRMED: 'modal.confirmedMsg',
          REVERTED: 'modal.revertedMsg',
          PENDING: 'modal.pendingMsg',
          UNKNOWN: 'modal.unknownMsg',
        };
        const description = descriptions[data.status] ? t(descriptions[data.status]) : t('modal.statusMsg', { status: data.status });
        appendMessage('agent', `${description}\n- **Tx Hash:** \`${data.tx_hash || t('modal.unknownHash')}\``, explorerLink);
        // Refresh wallet balances
        loadWalletInfo();
        loadNetworkStatus();
      } else {
        appendMessage('agent', t('modal.rejectedMsg'));
      }
    } catch (err) {
      alert(`Approval Error: ${err.message}`);
      elements.btnModalApprove.disabled = false;
      elements.btnModalReject.disabled = false;
      elements.btnModalApprove.querySelector('span:first-child').textContent = t('modal.btnApprove');
    }
  }

  return { submitApprovalAction };
}
