import { dashboardApi } from '../api.js';

export function createAssetsController(state, view, client = dashboardApi) {
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

  return { loadNetworkStatus, loadWalletInfo, loadPolicies };
}
