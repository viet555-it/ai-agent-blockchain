import { getLanguage } from './i18n.js';

/** State belongs to one dashboard; views receive it explicitly. */
export function createDashboardState() {
  return {
    wallet: null,
    network: null,
    policies: null,
    isProcessing: false,
    pendingApproval: null,
    activeApprovalParameters: null,
    sessionId: crypto.randomUUID(),
    theme: localStorage.getItem('ati_theme') || 'dark',
    language: getLanguage(),
    lastTimelineSteps: null,
    lastBaseFeeGwei: null,
    walletMode: false,
    walletController: null,
    historyView: null,
    historyLoading: false,
    followLatest: true,
  };
}
