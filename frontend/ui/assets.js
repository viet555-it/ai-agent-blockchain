import { t, onLanguageChange } from '../i18n.js';
import { guardrailReasons } from './guardrail-reasons.js';
import { displayDecimal } from '../api.js';
import { shortenAddress } from './format.js';
import { sameAddress } from '../wallet.js';

export function createAssetsView(state, elements) {
  let currentWhitelist = [];
  let lastTestBlockResult = null;
  let lastContractLimit = null;
  onLanguageChange(() => {
    if (lastTestBlockResult) renderTestBlockResult(lastTestBlockResult);
    renderContractLimit(lastContractLimit);
  });

  function updateNetworkLabels() {
    if (!state.network) return;
    elements.headerNetworkName.textContent = state.network.name;
    elements.modalNetwork.textContent = `${state.network.name} (${state.network.chain_id})`;
    const contractNetworkLabel = document.getElementById('contract-network-label');
    if (contractNetworkLabel) {
      contractNetworkLabel.textContent = t('network.smartContractOn', {
        network: state.network.name,
      });
    }
  }

  function renderNetwork(data) {
    state.network = data;

    elements.headerNetworkName.textContent = data.name;
    elements.badgeChainId.textContent = `Chain ${data.chain_id}`;
    updateNetworkLabels();
    elements.linkContractExplorer.hidden = !data.block_explorer_url || !data.contract_address;
    elements.linkContractExplorer.style.display = data.block_explorer_url && data.contract_address ? '' : 'none';
    if (!data.block_explorer_url || !data.contract_address) {
      elements.linkContractExplorer.removeAttribute('href');
    }

    if (data.contract_address) {
      elements.valContractAddress.textContent = data.contract_address;
      if (data.block_explorer_url) {
        elements.linkContractExplorer.href = `${data.block_explorer_url}/address/${data.contract_address}`;
      }
    }

    if (data.gas_info) {
      elements.valGasPrice.textContent = data.gas_info.gas_price_gwei || '--';
      const baseGwei = data.gas_info.base_fee_per_gas
        ? (data.gas_info.base_fee_per_gas / 1e9).toFixed(2)
        : 'N/A';
      state.lastBaseFeeGwei = baseGwei;
      elements.valBaseFee.textContent = t('network.baseFee', { fee: baseGwei });
    }

    if (data.rpc_health && data.rpc_health.length > 0) {
      const activeRpc = data.rpc_health[0];
      elements.rpcLatencyText.textContent = `RPC: ${activeRpc.latency_ms} ms`;
      if (activeRpc.latency_ms < 400) {
        elements.networkPulse.className = 'pulse-dot';
      } else {
        elements.networkPulse.className = 'pulse-dot amber';
      }
    }
  }

  function renderWallet(data) {
    state.wallet = data;

    elements.headerWalletAddress.textContent = shortenAddress(data.address);
    elements.valNativeBalance.textContent = displayDecimal(data.native_balance || '0');
    elements.valNativeBalance.title = data.native_balance || '0';
    elements.valNativeSymbol.textContent = data.native_symbol || 'ETH';
    elements.valTokenBalance.textContent = displayDecimal(data.token_balance || '0');
    elements.valTokenBalance.title = data.token_balance || '0';
  }

  function renderPolicies(data) {
    state.policies = data;
    if (elements.policyMaxLimit) {
      elements.policyMaxLimit.textContent = `${data.max_token_transfer_limit} AGNT`;
    }
  }

  function renderWhitelistTags(whitelist, onRemove) {
    currentWhitelist = [...whitelist];
    const container = document.getElementById('guardrail-whitelist-tags');
    if (!container) return;
    container.replaceChildren();
    const copyStatus = document.getElementById('whitelist-copy-status');
    if (copyStatus) copyStatus.textContent = '';

    if (currentWhitelist.length === 0) {
      const emptyNote = document.createElement('span');
      emptyNote.style.fontSize = '0.72rem';
      emptyNote.style.color = 'var(--text-dim)';
      emptyNote.textContent = '(Chưa có địa chỉ nào / Empty)';
      container.appendChild(emptyNote);
      return;
    }

    currentWhitelist.forEach((addr, idx) => {
      const tag = document.createElement('span');
      tag.className = 'whitelist-tag';
      tag.title = addr;

      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'whitelist-copy';
      copyBtn.textContent = shortenAddress(addr);
      copyBtn.title = `${t('header.copyWallet')}: ${addr}`;
      copyBtn.setAttribute('aria-label', copyBtn.title);
      copyBtn.addEventListener('click', async () => {
        if (copyStatus) copyStatus.textContent = '';
        try {
          await navigator.clipboard.writeText(addr);
          if (copyStatus && copyBtn.isConnected) copyStatus.textContent = t('header.walletCopied');
        } catch {
          if (copyStatus && copyBtn.isConnected) copyStatus.textContent = t('guardrail.copyFailed');
        }
      });

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.textContent = '×';
      removeBtn.title = t('guardrail.remove');
      removeBtn.setAttribute('aria-label', `${t('guardrail.remove')}: ${addr}`);
      removeBtn.addEventListener('click', () => {
        currentWhitelist.splice(idx, 1);
        renderWhitelistTags(currentWhitelist, onRemove);
        if (onRemove) onRemove(currentWhitelist);
      });

      tag.append(copyBtn, removeBtn);
      container.appendChild(tag);
    });
  }

  function renderGuardrailConfig(config, onWhitelistChange) {
    renderContractLimit(config.contract_transfer_limit);
    const inputPerTxNative = document.getElementById('input-per-tx-native');
    const inputDailyNative = document.getElementById('input-daily-native');
    const spentNative = document.getElementById('val-guardrail-spent-native');
    const remNative = document.getElementById('val-guardrail-rem-native');

    const inputPerTxToken = document.getElementById('input-per-tx-token');
    const inputDailyToken = document.getElementById('input-daily-token');
    const spentToken = document.getElementById('val-guardrail-spent-token');
    const remToken = document.getElementById('val-guardrail-rem-token');

    const checkEnforceWhitelist = document.getElementById('check-enforce-whitelist');
    const checkRequireAppApproval = document.getElementById('check-require-app-approval');

    if (inputPerTxNative) inputPerTxNative.value = config.per_tx_native_limit ?? 0.1;
    if (inputDailyNative) inputDailyNative.value = config.daily_native_limit ?? 0.5;
    if (spentNative) spentNative.textContent = config.daily_native_spent ?? '0';
    if (remNative) remNative.textContent = config.daily_native_remaining ?? config.daily_native_limit ?? '0.5';

    if (inputPerTxToken) inputPerTxToken.value = config.per_tx_token_limit ?? 100;
    if (inputDailyToken) inputDailyToken.value = config.daily_token_limit ?? 500;
    if (spentToken) spentToken.textContent = config.daily_token_spent ?? '0';
    if (remToken) remToken.textContent = config.daily_token_remaining ?? config.daily_token_limit ?? '500';

    if (checkEnforceWhitelist) checkEnforceWhitelist.checked = Boolean(config.enforce_whitelist);
    if (checkRequireAppApproval) checkRequireAppApproval.checked = config.require_app_approval !== false;

    renderWhitelistTags(config.recipient_whitelist || [], onWhitelistChange);
  }

  function renderContractLimit(ceiling) {
    lastContractLimit = ceiling;
    const note = document.getElementById('contract-limit-note');
    if (!note) return;
    note.textContent = ceiling ? t('guardrail.contractCeiling', { limit: ceiling.per_tx_limit }) : t('guardrail.contractUnavailable');
    const input = document.getElementById('input-per-tx-token');
    input.disabled = !ceiling;
    if (ceiling) input.max = ceiling.per_tx_limit;
    else input.removeAttribute('max');
    document.getElementById('btn-save-guardrail-config').disabled = !ceiling;
    const wallet = state.walletController;
    document.getElementById('contract-limit-form').hidden = !(ceiling && wallet?.ready && sameAddress(wallet.address, ceiling.owner));
    const ownerInput = document.getElementById('input-contract-limit');
    if (ceiling && ownerInput !== document.activeElement && !state.updatingContractLimit) ownerInput.value = ceiling.per_tx_limit;
    document.getElementById('btn-save-contract-limit').disabled = Boolean(state.updatingContractLimit);
  }

  function setGuardrailSaveStatus(message, isError = false) {
    const statusEl = document.getElementById('guardrail-save-status');
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.style.color = isError ? 'var(--danger, #ef4444)' : 'var(--success, #22c55e)';
    setTimeout(() => {
      if (statusEl.textContent === message) statusEl.textContent = '';
    }, 4000);
  }

  function renderTestBlockResult(data) {
    lastTestBlockResult = data;
    const resultBox = document.getElementById('test-block-result-box');
    const badge = document.getElementById('test-block-decision-badge');
    const reasonsList = document.getElementById('test-block-reasons-list');
    const detailsGrid = document.getElementById('test-block-details-grid');
    if (!resultBox || !badge || !reasonsList) return;

    resultBox.hidden = false;
    badge.className = 'panel-badge';

    if (data.decision === 'ALLOW') {
      badge.textContent = t('guardrail.decisionAllow');
      badge.classList.add('badge-allow');
    } else if (data.decision === 'REQUIRE_APPROVAL') {
      badge.textContent = t('guardrail.decisionRequireApproval');
      badge.classList.add('badge-require-approval');
    } else {
      badge.textContent = t('guardrail.decisionBlock');
      badge.classList.add('badge-block');
    }

    reasonsList.replaceChildren();
    guardrailReasons(data).forEach(r => {
      const li = document.createElement('li');
      li.textContent = r;
      reasonsList.appendChild(li);
    });

    if (detailsGrid && data.details) {
      detailsGrid.replaceChildren();
      const items = [
        { label: t('guardrail.perTxLimit'), val: data.details.per_tx_limit },
        { label: t('guardrail.dailyLimit'), val: data.details.daily_limit },
        { label: t('guardrail.spent24h'), val: data.details.daily_spent },
        { label: t('guardrail.remaining24h'), val: data.details.daily_remaining },
      ];
      items.forEach(item => {
        const d = document.createElement('div');
        d.innerHTML = `<span style="color:var(--text-dim);">${item.label}:</span> <b>${item.val}</b>`;
        detailsGrid.appendChild(d);
      });
    }
  }

  function showNetworkError() {
    elements.headerNetworkName.textContent = 'Offline / Error';
    elements.networkPulse.style.background = 'var(--danger)';
  }

  return {
    updateNetworkLabels,
    renderNetwork,
    renderWallet,
    renderPolicies,
    renderGuardrailConfig,
    renderWhitelistTags,
    setGuardrailSaveStatus,
    renderTestBlockResult,
    showNetworkError,
    getCurrentWhitelist: () => currentWhitelist,
  };
}
