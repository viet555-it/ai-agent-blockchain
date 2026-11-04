import { dashboardApi } from '../api.js';
import { t } from '../i18n.js';

export function createAssetsController(state, view, client = dashboardApi) {
  let activeWhitelist = [];
  let activeTokenAddress = null;
  let activeTokenLimits = {};
  let activeContractLimit = null;

  async function loadNetworkStatus() {
    try {
      view.renderNetwork(await client.networkStatus());
    } catch (error) {
      console.error('Failed to load network status:', error);
      view.showNetworkError();
    }
  }

  async function loadWalletInfo() {
    const generation = state.walletController?.generation;
    const address = state.walletController?.address;
    if (state.walletMode && !address) return;
    try {
      const data = await client.walletInfo(state.walletMode ? address : null);
      if (state.walletMode && !state.walletController.current(generation)) return;
      view.renderWallet(data);
      await loadGuardrailConfig();
    } catch (error) {
      console.error('Failed to load wallet info:', error);
    }
  }

  async function loadPolicies() {
    try {
      view.renderPolicies(await client.policies());
    } catch (error) {
      console.error('Failed to load guardrail policies:', error);
    }
  }

  async function loadGuardrailConfig() {
    const address = state.walletController?.address || state.wallet?.address;
    const generation = state.walletController?.generation;
    try {
      const data = await client.getGuardrailConfig(address);
      if (state.walletMode && !state.walletController.current(generation)) return;
      activeTokenAddress = data.token_address;
      activeContractLimit = data.contract_transfer_limit;
      activeTokenLimits = { ...(data.token_limits || {}) };
      activeWhitelist = [...(data.recipient_whitelist || [])];
      view.renderGuardrailConfig(data, updatedList => {
        activeWhitelist = updatedList;
      });
    } catch (error) {
      console.error('Failed to load guardrail config:', error);
    }
  }

  async function handleSaveGuardrailConfig(e) {
    if (e) e.preventDefault();
    const address = state.walletController?.address || state.wallet?.address;
    if (!address) {
      view.setGuardrailSaveStatus(t('wallet.gateSignIn'), true);
      return;
    }

    const perTxNative = parseFloat(document.getElementById('input-per-tx-native')?.value || '0.1');
    const dailyNative = parseFloat(document.getElementById('input-daily-native')?.value || '0.5');
    const perTxToken = parseFloat(document.getElementById('input-per-tx-token')?.value || '100');
    const dailyToken = parseFloat(document.getElementById('input-daily-token')?.value || '500');
    const enforceWhitelist = Boolean(document.getElementById('check-enforce-whitelist')?.checked);
    const requireAppApproval = Boolean(document.getElementById('check-require-app-approval')?.checked);

    const btn = document.getElementById('btn-save-guardrail-config');
    if (btn) btn.disabled = true;

    try {
      if (!activeContractLimit || perTxToken > Number(activeContractLimit.per_tx_limit)) throw new Error(t('guardrail.contractLimitError'));
      const tokenAddress = activeTokenAddress || state.wallet?.token_address || state.network?.contract_address;
      if (!/^0x[0-9a-f]{40}$/i.test(tokenAddress || '') || /^0x0{40}$/i.test(tokenAddress)) {
        throw new Error('AGNT contract is unavailable. Refresh blockchain data and try again.');
      }
      const payload = {
        wallet_address: address,
        per_tx_native_limit: perTxNative,
        daily_native_limit: dailyNative,
        token_limits: {
          ...activeTokenLimits,
          [tokenAddress.toLowerCase()]: {
            symbol: 'AGNT',
            per_tx_limit: perTxToken,
            daily_limit: dailyToken,
          },
        },
        recipient_whitelist: activeWhitelist,
        enforce_whitelist: enforceWhitelist,
        require_app_approval: requireAppApproval,
        approval_timeout_seconds: 600,
      };

      const res = await client.updateGuardrailConfig(payload);
      if (res && res.status === 'SAVED') {
        view.setGuardrailSaveStatus(t('guardrail.configSaved'), false);
        await loadGuardrailConfig();
      } else {
        view.setGuardrailSaveStatus(t('guardrail.configSaveError'), true);
      }
    } catch (err) {
      console.error('Save guardrail config error:', err);
      view.setGuardrailSaveStatus(`${t('guardrail.configSaveError')}: ${err.message}`, true);
    } finally {
      if (btn) btn.disabled = !activeContractLimit;
    }
  }

  async function handleContractLimit(e) {
    e.preventDefault();
    const wallet = state.walletController;
    if (!wallet?.ready || state.updatingContractLimit) return;
    const generation = wallet.generation;
    const provider = wallet.provider;
    const status = document.getElementById('contract-limit-status');
    const button = document.getElementById('btn-save-contract-limit');
    const amount = document.getElementById('input-contract-limit').value.trim();
    state.updatingContractLimit = true;
    let hash;
    button.disabled = true;
    status.textContent = t('guardrail.contractWaiting');
    try {
      const config = await client.getGuardrailConfig(wallet.address);
      if (!wallet.current(generation)) return;
      hash = await wallet.setTransferLimit(config.contract_transfer_limit, amount);
      if (!wallet.current(generation)) return;
      status.textContent = t('guardrail.contractPending', { hash });
      for (let attempt = 0; attempt < 60; attempt++) {
        const receipt = await provider.request({ method: 'eth_getTransactionReceipt', params: [hash] });
        if (!wallet.current(generation)) return;
        if (receipt) {
          if (BigInt(receipt.status) !== 1n) throw new Error(t('modal.revertedMsg'));
          status.textContent = t('guardrail.contractUpdated');
          await loadGuardrailConfig();
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
        if (!wallet.current(generation)) return;
      }
      // Keep the hash visible; a delayed receipt must never trigger a resend.
    } catch (error) {
      if (wallet.current(generation)) status.textContent = hash ? `${t('guardrail.contractPending', { hash })}\n${error.message}` : error.message;
    } finally {
      state.updatingContractLimit = false;
      button.disabled = false;
    }
  }

  async function handleTestBlock(e) {
    if (e) e.preventDefault();
    const operation = document.getElementById('select-test-operation')?.value || 'native_transfer';
    const amount = document.getElementById('input-test-amount')?.value?.trim();
    const recipient = document.getElementById('input-test-recipient')?.value?.trim();
    const address = state.walletController?.address || state.wallet?.address;

    if (!amount || !recipient) return;

    const btn = document.getElementById('btn-run-test-block');
    if (btn) {
      btn.disabled = true;
      btn.textContent = t('guardrail.testing');
    }

    try {
      const res = await client.testBlock({
        wallet_address: address || null,
        operation,
        amount,
        recipient,
      });
      view.renderTestBlockResult(res);
    } catch (err) {
      console.error('Test block error:', err);
      view.renderTestBlockResult({
        decision: 'BLOCK',
        is_allowed: false,
        requires_approval: false,
        reason_code: 'CHECK_FAILED',
        reasons: [],
      });
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = t('guardrail.btnTestBlock');
      }
    }
  }

  function handleAddWhitelist() {
    const input = document.getElementById('input-whitelist-address');
    if (!input) return;
    const val = input.value.trim();
    if (!val) return;
    if (!activeWhitelist.some(a => a.toLowerCase() === val.toLowerCase())) {
      activeWhitelist.push(val);
      view.renderWhitelistTags(activeWhitelist, updated => {
        activeWhitelist = updated;
      });
    }
    input.value = '';
  }

  function bindGuardrailEvents() {
    document.getElementById('contract-limit-form').addEventListener('submit', handleContractLimit);
    const formConfig = document.getElementById('guardrail-config-form');
    if (formConfig) formConfig.addEventListener('submit', handleSaveGuardrailConfig);

    const btnAddWhitelist = document.getElementById('btn-add-whitelist');
    if (btnAddWhitelist) btnAddWhitelist.addEventListener('click', handleAddWhitelist);

    const formTestBlock = document.getElementById('form-test-block');
    if (formTestBlock) formTestBlock.addEventListener('submit', handleTestBlock);
  }

  return {
    loadNetworkStatus,
    loadWalletInfo,
    loadPolicies,
    loadGuardrailConfig,
    bindGuardrailEvents,
  };
}
