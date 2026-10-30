import { t } from '../i18n.js';

export function createApprovalModal(state, elements) {
  function openApprovalModal(approval, guardrailResult) {
    document.getElementById('modal-sender').textContent = approval.parameters.sender || state.wallet?.address || '--';
    state.pendingApproval = approval;
    state.activeApprovalParameters = approval.parameters;

    elements.modalOpName.textContent = approval.operation;
    elements.modalRecipient.textContent = approval.parameters.recipient || 'N/A';
    elements.modalAmount.textContent = `${approval.parameters.amount || '0'} ${approval.parameters.token_symbol || 'AGNT'}`;

    if (guardrailResult && guardrailResult.simulation_result) {
      const sim = guardrailResult.simulation_result;
      elements.modalSimResult.textContent = sim.isValid
        ? t('modal.simValidDetails', { chain: approval.parameters.chain_id ?? '?', fee: sim.max_fee_wei ?? '?' })
        : t('modal.simRevert', { reason: sim.reason });
      elements.modalGas.textContent = String(sim.gas_limit ?? sim.gas_estimate ?? '--');
      elements.modalSimResult.style.color = sim.isValid ? 'var(--success)' : 'var(--danger)';
    } else {
      elements.modalGas.textContent = '--';
      elements.modalSimResult.textContent = t('modal.simPreflightPassed');
      elements.modalSimResult.style.color = 'var(--success)';
    }

    elements.btnModalApprove.disabled = false;
    elements.btnModalReject.disabled = false;
    elements.btnModalApprove.querySelector('span:first-child').textContent = t('modal.btnApprove');
    elements.approvalModal.classList.add('open');
  }

  function closeApprovalModal() {
    elements.approvalModal.classList.remove('open');
    state.pendingApproval = null;
    state.activeApprovalParameters = null;
  }


  return { openApprovalModal, closeApprovalModal };
}
