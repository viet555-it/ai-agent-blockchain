/** Compose dashboard views and controllers, then start the application. */
import { dashboardApi } from './api.js';
import { initializeI18n, t } from './i18n.js';
import { createDashboardState } from './state.js';
import { createAssetsController } from './controllers/assets.js';
import { createApprovalController } from './controllers/approvals.js';
import { createChatController } from './controllers/chat.js';
import { createWalletSession } from './controllers/wallet-session.js';
import { collectElements } from './ui/elements.js';
import { createThemeView } from './ui/theme.js';
import { createLanguageView } from './ui/language.js';
import { createAssetsView } from './ui/assets.js';
import { createChatView } from './ui/chat.js';
import { createTimelineView } from './ui/timeline.js';
import { createApprovalModal } from './ui/approval-modal.js';
import { createWalletGate } from './ui/wallet-gate.js';
import { bindDashboardEvents } from './ui/events.js';
import { observeDashboardLayout } from './ui/layout.js';

async function bootstrap() {
  const state = createDashboardState();
  const elements = collectElements();
  const theme = createThemeView(state, elements);
  const chat = createChatView(state, elements);
  const timeline = createTimelineView(state, elements);
  const approval = createApprovalModal(state, elements);
  const assetsView = createAssetsView(state, elements);
  const assets = createAssetsController(state, assetsView);
  const gate = createWalletGate(state, elements);
  const language = createLanguageView(state, elements, {
    updateNetworkLabels: assetsView.updateNetworkLabels,
    renderTimeline: timeline.renderTimeline,
  });
  const chatController = createChatController(state, elements, {
    ...chat,
    ...timeline,
    openApprovalModal: approval.openApprovalModal,
    renderWalletGate: gate.renderWalletGate,
  });
  const approvalController = createApprovalController(state, elements, {
    appendMessage: chat.appendMessage,
    closeApprovalModal: approval.closeApprovalModal,
    loadWalletInfo: assets.loadWalletInfo,
    loadNetworkStatus: assets.loadNetworkStatus,
  });
  const walletSession = createWalletSession(state, elements, {
    appendMessage: chat.appendMessage,
    ...timeline,
    ...approval,
    loadWalletInfo: assets.loadWalletInfo,
    renderWalletGate: gate.renderWalletGate,
  });

  observeDashboardLayout(state, elements);
  await initializeI18n();
  theme.applyTheme(state.theme);
  theme.initIcons();
  language.updateLanguageUI(state.language);
  bindDashboardEvents(state, elements, {
    toggleTheme: theme.toggleTheme,
    ...language,
    ...chatController,
    ...assets,
    ...approvalController,
    closeApprovalModal: approval.closeApprovalModal,
  });
  chat.appendMessage('agent', t('chat.welcomeGreeting'));

  try {
    await walletSession.initializeWalletMode(await dashboardApi.health());
  } catch (error) {
    elements.btnSendMessage.disabled = true;
    chat.appendMessage('agent', error.message);
    return;
  }

  await Promise.all([assets.loadNetworkStatus(), assets.loadWalletInfo(), assets.loadPolicies()]);
  setInterval(() => {
    if (!state.isProcessing) {
      assets.loadNetworkStatus();
      assets.loadWalletInfo();
      if (state.walletMode) state.historyView.refreshTransactions().catch(() => {});
    }
  }, 20000);
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
