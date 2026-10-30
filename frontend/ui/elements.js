/** Resolve DOM references once per dashboard instance. */
export function collectElements() {
  return {
    // Brand & Header
    appBrandIcon: document.getElementById('app-brand-icon'),
    headerNetworkName: document.getElementById('header-network-name'),
    networkPulse: document.getElementById('network-pulse'),
    rpcLatencyText: document.getElementById('rpc-latency-text'),
    headerWalletAddress: document.getElementById('header-wallet-address'),
    btnCopyHeaderWallet: document.getElementById('btn-copy-header-wallet'),

    // Theme & Language Controls
    btnToggleTheme: document.getElementById('btn-toggle-theme'),
    iconThemeBtn: document.getElementById('icon-theme-btn'),
    themeLabelText: document.getElementById('theme-label-text'),
    btnToggleLang: document.getElementById('btn-toggle-lang'),
    iconLangBtn: document.getElementById('icon-lang-btn'),
    langOptEn: document.getElementById('lang-opt-en'),
    langOptVi: document.getElementById('lang-opt-vi'),

    // Assets Panel
    iconBlockchainPanel: document.getElementById('icon-blockchain-panel'),
    btnRefreshAssets: document.getElementById('btn-refresh-assets'),
    valNativeBalance: document.getElementById('val-native-balance'),
    valNativeSymbol: document.getElementById('val-native-symbol'),
    badgeChainId: document.getElementById('badge-chain-id'),
    valTokenBalance: document.getElementById('val-token-balance'),
    valContractAddress: document.getElementById('val-contract-address'),
    linkContractExplorer: document.getElementById('link-contract-explorer'),
    iconExternalContract: document.getElementById('icon-external-contract'),
    valGasPrice: document.getElementById('val-gas-price'),
    valBaseFee: document.getElementById('val-base-fee'),
    iconGuardrailBadge: document.getElementById('icon-guardrail-badge'),
    policyMaxLimit: document.getElementById('policy-max-limit'),

    // Chat Workspace
    iconChatPanel: document.getElementById('icon-chat-panel'),
    chatHistory: document.getElementById('chat-history'),
    chatForm: document.getElementById('chat-form'),
    chatInput: document.getElementById('chat-input'),
    btnSendMessage: document.getElementById('btn-send-message'),
    iconSendBtn: document.getElementById('icon-send-btn'),
    promptChips: document.getElementById('prompt-chips'),

    // Timeline
    iconActivityPanel: document.getElementById('icon-activity-panel'),
    timelineContainer: document.getElementById('timeline-container'),
    timelineEmptyState: document.getElementById('timeline-empty-state'),
    timelineList: document.getElementById('timeline-list'),
    timelineStepCount: document.getElementById('timeline-step-count'),
    iconEmptyTimeline: document.getElementById('icon-empty-timeline'),

    // Approval Modal
    approvalModal: document.getElementById('approval-modal'),
    iconModalShield: document.getElementById('icon-modal-shield'),
    modalOpName: document.getElementById('modal-op-name'),
    modalNetwork: document.getElementById('modal-network'),
    modalRecipient: document.getElementById('modal-recipient'),
    modalAmount: document.getElementById('modal-amount'),
    modalGas: document.getElementById('modal-gas'),
    modalGuardrailBanner: document.getElementById('modal-guardrail-banner'),
    iconModalCheck: document.getElementById('icon-modal-check'),
    modalGuardrailTitle: document.getElementById('modal-guardrail-title'),
    modalGuardrailDetails: document.getElementById('modal-guardrail-details'),
    modalSimResult: document.getElementById('modal-sim-result'),
    btnModalReject: document.getElementById('btn-modal-reject'),
    btnModalApprove: document.getElementById('btn-modal-approve'),
    iconModalApprove: document.getElementById('icon-modal-approve'),
  };
}
