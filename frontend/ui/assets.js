import { t } from '../i18n.js';
import { displayDecimal } from '../api.js';
import { shortenAddress } from './format.js';

export function createAssetsView(state, elements) {
  function updateNetworkLabels() {
    if (!state.network) return;
    elements.headerNetworkName.textContent = state.network.name;
    elements.modalNetwork.textContent = `${state.network.name} (${state.network.chain_id})`;
    document.getElementById('contract-network-label').textContent = t('network.smartContractOn', {
      network: state.network.name,
    });
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
    elements.policyMaxLimit.textContent = `${data.max_token_transfer_limit} AGNT`;
  }

  function showNetworkError() {
    elements.headerNetworkName.textContent = 'Offline / Error';
    elements.networkPulse.style.background = 'var(--danger)';
  }

  return { updateNetworkLabels, renderNetwork, renderWallet, renderPolicies, showNetworkError };
}
