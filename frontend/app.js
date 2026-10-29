/**
 * AI Agent Blockchain Dashboard Application Logic
 * Integrates with FastAPI backend, Policy Engine, Web3 Services,
 * Dynamic Theming, and Reactive Internationalization (i18n).
 */
import { icons } from './icons.js';
import { api, displayDecimal } from './api.js';
import { WalletController } from './wallet.js';
import { HistoryView } from './history.js';
import {
  t,
  getLanguage,
  setLanguage,
  onLanguageChange,
  updateDomTranslations,
  initializeI18n,
} from './i18n.js';

const API_BASE = window.location.origin;

// Application State
const state = {
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

// DOM Elements
const elements = {
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

/**
 * Initialize SVG icons
 */
function initIcons() {
  elements.appBrandIcon.innerHTML = icons.bot;
  elements.btnCopyHeaderWallet.innerHTML = icons.copy;
  elements.iconBlockchainPanel.innerHTML = icons.wallet;
  elements.btnRefreshAssets.innerHTML = icons.refresh;
  elements.iconExternalContract.innerHTML = icons.externalLink;
  elements.iconGuardrailBadge.innerHTML = icons.shield;
  elements.iconChatPanel.innerHTML = icons.bot;
  elements.iconSendBtn.innerHTML = icons.send;
  elements.iconActivityPanel.innerHTML = icons.activity;
  elements.iconEmptyTimeline.innerHTML = icons.layers;
  elements.iconModalShield.innerHTML = icons.shield;
  elements.iconModalCheck.innerHTML = icons.checkCircle;
  elements.iconModalApprove.innerHTML = icons.checkCircle;
  elements.iconLangBtn.innerHTML = icons.globe;
  updateThemeIcon();
}

/**
 * Apply and synchronize theme state
 */
function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  try {
    localStorage.setItem('ati_theme', theme);
  } catch (e) {
    console.warn('Unable to persist theme:', e);
  }
  updateThemeIcon();
}

function updateThemeIcon() {
  if (state.theme === 'light') {
    elements.iconThemeBtn.innerHTML = icons.moon;
    elements.themeLabelText.textContent = 'Light';
  } else {
    elements.iconThemeBtn.innerHTML = icons.sun;
    elements.themeLabelText.textContent = 'Dark';
  }
}

/**
 * Toggle between Dark and Light mode
 */
function toggleTheme() {
  const nextTheme = state.theme === 'dark' ? 'light' : 'dark';
  applyTheme(nextTheme);
}

/**
 * Update Language UI Indicator and refresh dynamic text
 */
function updateLanguageUI(lang) {
  state.language = lang;
  if (lang === 'vi') {
    elements.langOptVi.classList.add('active');
    elements.langOptEn.classList.remove('active');
  } else {
    elements.langOptEn.classList.add('active');
    elements.langOptVi.classList.remove('active');
  }

  // Update all declarative elements in DOM
  updateDomTranslations();
  updateNetworkLabels();

  // Update dynamic prompt chip queries
  elements.promptChips.querySelectorAll('.prompt-chip').forEach(chip => {
    const key = chip.getAttribute('data-prompt-key');
    if (key) {
      chip.setAttribute('data-prompt', t(key));
    }
  });

  // Re-render base fee if present
  if (state.lastBaseFeeGwei !== null) {
    elements.valBaseFee.textContent = t('network.baseFee', { fee: state.lastBaseFeeGwei });
  }

  // Re-render timeline if steps exist
  if (state.lastTimelineSteps && state.lastTimelineSteps.length > 0) {
    renderTimeline(state.lastTimelineSteps);
  } else {
    elements.timelineStepCount.textContent = t('timeline.stepsCount', { current: 0, total: 9 });
  }

  // Update document title
  document.title = lang === 'vi'
    ? 'AI Agent với Công cụ Blockchain | Web3 Security & Guardrail Engine'
    : 'AI Agent with Blockchain Tools | Web3 Security & Guardrail Engine';
}

/**
 * Toggle between Vietnamese and English
 */
function toggleLanguage() {
  const nextLang = getLanguage() === 'en' ? 'vi' : 'en';
  setLanguage(nextLang);
}

/**
 * Shorten an Ethereum address for display (0x1234...abcd)
 */
function shortenAddress(addr) {
  if (!addr || addr.length < 10) return addr || '0x...';
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function updateNetworkLabels() {
  if (!state.network) return;
  elements.headerNetworkName.textContent = state.network.name;
  elements.modalNetwork.textContent = `${state.network.name} (${state.network.chain_id})`;
  document.getElementById('contract-network-label').textContent = t('network.smartContractOn', {
    network: state.network.name,
  });
}

/**
 * Fetch and update network status & RPC latency
 */
async function loadNetworkStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/network/status`);
    if (!res.ok) throw new Error('Network status unreachable');
    const data = await res.json();
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
  } catch (err) {
    console.error('Failed to load network status:', err);
    elements.headerNetworkName.textContent = 'Offline / Error';
    elements.networkPulse.style.background = 'var(--danger)';
  }
}

/**
 * Fetch wallet balance and token info
 */
async function loadWalletInfo() {
  const generation = state.walletController?.generation;
  const address = state.walletController?.address;
  if (state.walletMode && !address) return;
  try {
    const res = await fetch(`${API_BASE}/api/wallet/info${state.walletMode ? `?address=${encodeURIComponent(address)}` : ''}`);
    if (!res.ok) throw new Error('Wallet info unreachable');
    const data = await res.json();
    if (state.walletMode && !state.walletController.current(generation)) return;
    state.wallet = data;

    elements.headerWalletAddress.textContent = shortenAddress(data.address);
    elements.valNativeBalance.textContent = displayDecimal(data.native_balance || '0');
    elements.valNativeBalance.title = data.native_balance || '0';
    elements.valNativeSymbol.textContent = data.native_symbol || 'ETH';
    elements.valTokenBalance.textContent = displayDecimal(data.token_balance || '0');
    elements.valTokenBalance.title = data.token_balance || '0';
  } catch (err) {
    console.error('Failed to load wallet info:', err);
  }
}

/**
 * Fetch guardrail policies
 */
async function loadPolicies() {
  try {
    const res = await fetch(`${API_BASE}/api/guardrail/policies`);
    if (!res.ok) return;
    const data = await res.json();
    state.policies = data;
    elements.policyMaxLimit.textContent = `${data.max_token_transfer_limit} AGNT`;
  } catch (err) {
    console.error('Failed to load guardrail policies:', err);
  }
}

/**
 * Format markdown text (bold, code block, quotes, links) to safe HTML
 */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function formatMarkdown(text) {
  if (!text) return '';
  let formatted = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Bold
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Inline code
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="mono">$1</code>');
  // Block quotes
  formatted = formatted.replace(/^>\s*(.*?)$/gm, '<blockquote>$1</blockquote>');
  // Newlines
  formatted = formatted.replace(/\n/g, '<br>');

  return formatted;
}

/**
 * Append chat message to history
 */
function appendMessage(sender, text, extraHtml = '') {
  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${sender}`;

  const avatar = document.createElement('div');
  avatar.className = `avatar ${sender === 'user' ? 'user-avatar' : 'agent-avatar'}`;
  avatar.innerHTML = sender === 'user' ? icons.user : icons.bot;

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  bubble.innerHTML = `<div>${formatMarkdown(text)}</div>${extraHtml}`;

  msgDiv.appendChild(avatar);
  msgDiv.appendChild(bubble);

  elements.chatHistory.appendChild(msgDiv);
  state.followLatest = true;
  elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
  return bubble;
}

/**
 * Render typing indicator with localized message
 */
function showTypingIndicator() {
  const typingDiv = document.createElement('div');
  typingDiv.className = 'chat-message agent';
  typingDiv.id = 'typing-indicator';

  const avatar = document.createElement('div');
  avatar.className = 'avatar agent-avatar';
  avatar.innerHTML = icons.bot;

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';
  bubble.innerHTML = `
    <div style="display: flex; gap: 0.35rem; align-items: center; padding: 0.3rem 0;">
      <span class="pulse-dot" style="width: 6px; height: 6px;"></span>
      <span class="pulse-dot" style="width: 6px; height: 6px; animation-delay: 200ms;"></span>
      <span class="pulse-dot" style="width: 6px; height: 6px; animation-delay: 400ms;"></span>
      <span style="font-size: 0.8rem; color: var(--text-dim); margin-left: 0.45rem;">
        ${t('chat.analyzing')}
      </span>
    </div>
  `;

  typingDiv.appendChild(avatar);
  typingDiv.appendChild(bubble);
  elements.chatHistory.appendChild(typingDiv);
  elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

/**
 * Render Agent Workflow Timeline
 *
 * FIX FOR INCORRECT STEP NUMBERING:
 * 1. Explicitly sort timelineSteps by execution sequence:
 *    stepOrder || step_number || timestamp || id.
 * 2. Bind the displayed step badge strictly to the normalized 1-based index (idx + 1),
 *    preventing skipped numbers or corrupt numbering during dynamic/async updates or filtering.
 * 3. Localize step names and statuses reactively via i18n engine.
 */
function renderTimeline(timelineSteps) {
  if (!timelineSteps || timelineSteps.length === 0) {
    state.lastTimelineSteps = null;
    elements.timelineEmptyState.style.display = 'block';
    elements.timelineList.style.display = 'none';
    elements.timelineStepCount.textContent = t('timeline.stepsCount', { current: 0, total: 9 });
    return;
  }

  // Explicit sort by execution sequence
  const sortedSteps = [...timelineSteps].sort((a, b) => {
    const orderA = a.stepOrder ?? a.step_number ?? (a.timestamp ? a.timestamp * 1000 : 0);
    const orderB = b.stepOrder ?? b.step_number ?? (b.timestamp ? b.timestamp * 1000 : 0);
    if (orderA !== orderB) return orderA - orderB;
    return (a.timestamp || 0) - (b.timestamp || 0);
  });

  state.lastTimelineSteps = sortedSteps;

  elements.timelineEmptyState.style.display = 'none';
  elements.timelineList.style.display = 'flex';
  elements.timelineList.innerHTML = '';
  elements.timelineStepCount.textContent = t('timeline.stepsCount', {
    current: sortedSteps.length,
    total: 9,
  });

  sortedSteps.forEach((step, idx) => {
    // 1-based normalized index for sequential display
    const normalizedStepNum = idx + 1;
    const statusKey = step.status || 'INFO';
    const statusClass = statusKey.toLowerCase().replace('_', '-');

    // Translate step name and status
    const translatedName = t(`steps.${step.name}`, {}, step.name);
    const translatedStatus = t(`status.${statusKey}`, {}, statusKey);
    const stepTooltip = t('timeline.stepTooltip', { num: normalizedStepNum });
    const viewPayloadText = t('timeline.viewPayload');
    const hidePayloadText = t('timeline.hidePayload');
    const toolLabelText = t('timeline.toolLabel');

    const item = document.createElement('div');
    item.className = `timeline-item ${statusClass}`;

    const stepId = `step-details-${idx}`;

    item.innerHTML = `
      <div class="step-num-badge" title="${stepTooltip}" aria-label="${stepTooltip}">
        ${normalizedStepNum}
      </div>
      <div class="step-content">
        <div class="step-header">
          <span class="step-name">${escapeHtml(translatedName)}</span>
          <span class="step-badge ${statusClass}">${escapeHtml(translatedStatus)}</span>
        </div>
        ${step.duration_ms ? `<div class="step-duration">${step.duration_ms} ms</div>` : ''}
        ${step.tool_name ? `<div class="step-tool-tag">${toolLabelText} <strong>${escapeHtml(step.tool_name)}</strong></div>` : ''}
        
        ${step.result || step.sanitized_parameters || step.error ? `
          <button type="button" class="step-details-toggle" data-target="${stepId}">
            <span>${icons.chevronDown}</span>
            <span class="toggle-label">${viewPayloadText}</span>
          </button>
          <div class="step-details-box" id="${stepId}">
            ${escapeHtml(JSON.stringify(step.result || step.sanitized_parameters || { error: step.error }, null, 2))}
          </div>
        ` : ''}
      </div>
    `;

    elements.timelineList.appendChild(item);
  });

  // Attach toggle listeners with localized labels
  elements.timelineList.querySelectorAll('.step-details-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const box = document.getElementById(targetId);
      const labelSpan = btn.querySelector('.toggle-label');
      if (box) {
        box.classList.toggle('open');
        const isOpen = box.classList.contains('open');
        btn.querySelector('span:first-child').innerHTML = isOpen ? icons.chevronUp : icons.chevronDown;
        if (labelSpan) {
          labelSpan.textContent = isOpen ? t('timeline.hidePayload') : t('timeline.viewPayload');
        }
      }
    });
  });
}

/**
 * Open Transaction Review and Approval Modal
 */
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

/**
 * Submit Approval Action (Approve or Reject)
 */
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
    const res = await fetch(`${API_BASE}/api/approval/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approval_id: approvalId,
        action: action,
        parameters: params,
        session_id: state.sessionId,
        reviewer_comment: action === 'APPROVE' 
          ? 'Approved by user via dashboard' 
          : 'Rejected by user',
      }),
    });

    let data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Approval submission failed');

    // Receipt polling never resubmits APPROVE or broadcasts another transaction.
    for (let attempt = 0; action === 'APPROVE' && data.status === 'PENDING' && attempt < 8; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      const statusRes = await fetch(`${API_BASE}/api/approval/${encodeURIComponent(approvalId)}`, {
        headers: { 'X-Session-ID': state.sessionId },
      });
      if (!statusRes.ok) break;
      data = await statusRes.json();
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

/**
 * Handle sending a chat message
 */
async function handleSendMessage(query) {
  if (!query || !query.trim() || state.isProcessing) return;
  const wallet = state.walletController;
  const generation = wallet?.generation;
  const conversation = wallet?.conversation;
  const epoch = state.historyView?.epoch;
  const current = () => !state.walletMode || (wallet.current(generation) && wallet.conversation === conversation && state.historyView.epoch === epoch);
  if (state.walletMode && (!wallet.ready || !conversation || state.historyView.readOnly)) {
    appendMessage('agent', t('wallet.loginRequired'));
    return;
  }

  state.isProcessing = true;
  elements.btnSendMessage.disabled = true;
  elements.chatInput.value = '';

  // Append user message
  appendMessage('user', query);
  showTypingIndicator();

  try {
    let data;
    if (state.walletMode) {
      const context = wallet.context;
      const requestId = crypto.randomUUID();
      const result = await api(`/history/conversations/${conversation}/turns`, { method: 'POST', body: {
        query, context_id: context.id, generation: context.generation, client_request_id: requestId,
      } });
      if (!current()) return;
      data = result.response;
      if (!data) throw new Error(t('wallet.turnStatus', { status: result.status }));
    } else {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query,
          wallet_address: state.wallet ? state.wallet.address : null,
          session_id: state.sessionId,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to communicate with AI Agent');
      }

      data = await res.json();
    }
    if (!current()) return;
    removeTypingIndicator();

    // Extra RAG citation card if returned
    let ragCitationHtml = '';
    if (data.rag_result && data.rag_result.has_relevant_context && data.rag_result.documents.length > 0) {
      const doc = data.rag_result.documents[0];
      ragCitationHtml = `
        <div class="rag-citation">
          <div class="rag-header">
            <span>${icons.bookOpen} ${t('chat.ragTitle')}</span>
            <span>${t('chat.ragSimilarity', { score: Number(doc.score).toFixed(3) })}</span>
          </div>
          <div class="rag-body">${escapeHtml(doc.excerpt)}</div>
          <div class="rag-source">${escapeHtml(t('chat.ragSource', { title: doc.title, file: doc.source_file }))}</div>
        </div>
      `;
    }

    // Append Agent reply
    appendMessage('agent', data.reply, ragCitationHtml);

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
    elements.btnSendMessage.disabled = state.walletMode && !wallet.ready;
    elements.chatInput.focus();
    renderWalletGate();
  }
}

/**
 * Setup Event Listeners
 */
function setupEventListeners() {
  // Theme Toggle
  elements.btnToggleTheme.addEventListener('click', toggleTheme);

  // Language Toggle
  elements.btnToggleLang.addEventListener('click', toggleLanguage);

  // Subscribe to i18n changes
  onLanguageChange((lang) => {
    updateLanguageUI(lang);
  });

  // Chat form submit
  elements.chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const query = elements.chatInput.value.trim();
    handleSendMessage(query);
  });

  // Prompt suggestions
  elements.promptChips.querySelectorAll('.prompt-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) handleSendMessage(prompt);
    });
  });

  // Refresh assets
  elements.btnRefreshAssets.addEventListener('click', () => {
    elements.btnRefreshAssets.style.transform = 'rotate(180deg)';
    Promise.all([loadNetworkStatus(), loadWalletInfo(), loadPolicies()]).finally(() => {
      setTimeout(() => { elements.btnRefreshAssets.style.transform = 'none'; }, 300);
    });
  });

  // Copy header wallet
  elements.btnCopyHeaderWallet.addEventListener('click', () => {
    if (state.wallet && state.wallet.address) {
      navigator.clipboard.writeText(state.wallet.address);
      const original = elements.btnCopyHeaderWallet.innerHTML;
      elements.btnCopyHeaderWallet.innerHTML = icons.checkCircle;
      elements.btnCopyHeaderWallet.title = t('header.walletCopied');
      setTimeout(() => {
        elements.btnCopyHeaderWallet.innerHTML = original;
        elements.btnCopyHeaderWallet.title = t('header.copyWallet');
      }, 1500);
    }
  });

  // Modal actions
  elements.btnModalApprove.addEventListener('click', () => submitApprovalAction('APPROVE'));
  elements.btnModalReject.addEventListener('click', () => submitApprovalAction('REJECT'));

  // Close modal on escape key
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && elements.approvalModal.classList.contains('open')) {
      closeApprovalModal();
    }
  });
}

/**
 * Initial greeting message
 */
function greetUser() {
  appendMessage('agent', t('chat.welcomeGreeting'));
}

function clearWalletView() {
  state.followLatest = true;
  elements.chatHistory.replaceChildren();
  closeApprovalModal();
  state.isProcessing = false;
  state.lastTimelineSteps = null;
  elements.timelineList.replaceChildren();
  elements.timelineList.style.display = 'none';
  elements.timelineEmptyState.style.display = '';
  elements.timelineStepCount.textContent = '0 / 9';
  elements.btnSendMessage.disabled = state.walletMode && (!state.walletController.ready || state.historyView?.readOnly);
  renderWalletGate();
}

function renderWalletGate() {
  if (!state.walletMode) return;
  const wallet = state.walletController;
  const blocked = !wallet.ready || !wallet.conversation || state.historyView?.readOnly || state.historyLoading;
  const busy = wallet.connecting || wallet.authenticating || state.historyLoading;
  const gate = document.getElementById('wallet-chat-gate');
  gate.hidden = !blocked;
  let message = 'gateConnect', action = 'connectSignIn';
  if (!wallet.providers.size) { message = 'noProvider'; action = 'detectWallet'; }
  else if (wallet.status === 'wrongNetwork') { message = 'gateNetwork'; }
  else if (wallet.address && !wallet.ready) { message = 'gateSignIn'; }
  else if (wallet.ready) { message = state.historyLoading ? 'loadingChat' : state.historyView?.readOnly ? 'oldChat' : 'gateNewChat'; action = 'newChat'; }
  document.getElementById('wallet-chat-guidance').textContent = t(`wallet.${message}`, { chain: wallet.expectedChain });
  const button = document.getElementById('wallet-chat-action');
  button.textContent = t(`wallet.${action}`);
  button.disabled = busy;
  elements.chatInput.disabled = blocked || state.isProcessing;
  elements.btnSendMessage.disabled = blocked || state.isProcessing;
  elements.promptChips.querySelectorAll('button').forEach(button => { button.disabled = blocked || state.isProcessing; });
  for (const id of ['history-new', 'history-rename', 'history-archive', 'conversation-list']) {
    document.getElementById(id).disabled = !wallet.ready || state.historyLoading;
  }
  const controls = document.getElementById('wallet-controls');
  const agentReady = wallet.ready && wallet.conversation && !state.historyLoading && !state.historyView?.readOnly;
  controls.dataset.ready = String(Boolean(agentReady));
  if (wallet.ready) document.getElementById('wallet-status').textContent = t(`wallet.${state.historyLoading ? 'loadingChat' : agentReady ? 'ready' : 'gateNewChat'}`);
}

async function initializeWalletMode(health) {
  state.walletMode = health.wallet_history_enabled;
  if (!state.walletMode) return;
  const wallet = new WalletController(health.chain_id);
  state.walletController = wallet;
  const controls = document.getElementById('wallet-controls');
  controls.hidden = false;
  document.getElementById('wallet-chip').hidden = true;
  document.getElementById('wallet-history').hidden = false;
  const reportError = error => {
    const messages = { 4001: 'rejectedRequest', '-32002': 'pendingRequest', 4902: 'addNetworkFirst', ORIGIN: 'wrongOrigin', AUTH_REQUIRED: 'gateSignIn', DEPLOYMENT_UNAVAILABLE: health.chain_id === 31337 ? 'deploymentUnavailable' : undefined };
    const message = messages[error.code];
    renderWalletGate();
    controls.dataset.ready = 'false';
    document.getElementById('wallet-status').textContent = message ? t(`wallet.${message}`) : error.message;
  };
  const history = new HistoryView(wallet, { clear: clearWalletView, append: appendMessage,
    timeline: renderTimeline, approval: openApprovalModal, error: reportError });
  state.historyView = history;
  let generation = -1;
  let contextId = null;
  const providerSelect = document.getElementById('wallet-provider');
  const providers = () => {
    const selected = providerSelect.value;
    providerSelect.replaceChildren();
    for (const [id, item] of wallet.providers) {
      const option = document.createElement('option');
      option.value = id;
      option.textContent = item.name;
      providerSelect.append(option);
    }
    if (wallet.providers.has(selected)) providerSelect.value = selected;
    providerSelect.hidden = wallet.ready || wallet.providers.size <= 1;
    renderWalletGate();
  };
  const update = () => {
    if (generation !== wallet.generation) {
      generation = wallet.generation;
      document.getElementById('wallet-menu').open = false;
      state.historyLoading = false;
      contextId = null;
      history.clear();
      state.wallet = null;
      elements.headerWalletAddress.textContent = wallet.address ? shortenAddress(wallet.address) : '--';
      elements.valNativeBalance.textContent = '--';
      elements.valTokenBalance.textContent = '--';
    }
    elements.headerWalletAddress.textContent = wallet.address ? shortenAddress(wallet.address) : '--';
    document.getElementById('wallet-status').textContent = t(`wallet.${wallet.status}`);
    document.getElementById('wallet-connect').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
    document.getElementById('wallet-switch').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
    document.getElementById('wallet-connect').hidden = wallet.ready;
    document.getElementById('wallet-connect').textContent = t(`wallet.${wallet.connecting || wallet.authenticating ? 'confirmInWallet' : 'connectSignIn'}`);
    document.getElementById('wallet-menu').hidden = !wallet.ready;
    document.getElementById('wallet-menu-address').textContent = shortenAddress(wallet.address);
    document.getElementById('wallet-switch').hidden = !wallet.address;
    document.getElementById('wallet-disconnect').hidden = !wallet.address;
    document.getElementById('wallet-provider').disabled = wallet.connecting || wallet.authenticating || wallet.signing;
    document.getElementById('wallet-provider').hidden = wallet.ready || wallet.providers.size <= 1;
    elements.btnSendMessage.disabled = !wallet.ready || state.isProcessing || history.readOnly;
    if (wallet.ready && contextId !== wallet.context.id) {
      contextId = wallet.context.id;
      const expectedGeneration = wallet.generation;
      state.historyLoading = true;
      loadWalletInfo();
      history.initialize().catch(error => { if (wallet.current(expectedGeneration)) reportError(error); }).finally(() => {
        if (wallet.current(expectedGeneration)) { state.historyLoading = false; renderWalletGate(); }
      });
    }
    renderWalletGate();
  };
  wallet.addEventListener('change', update);
  wallet.addEventListener('error', event => reportError(event.detail));
  wallet.addEventListener('providers', providers);
  onLanguageChange(update);
  document.getElementById('wallet-connect').addEventListener('click', () => wallet.connectAndSignIn(providerSelect.value).catch(reportError));
  document.getElementById('wallet-switch').addEventListener('click', () => {
    document.getElementById('wallet-menu').open = false;
    wallet.connectAndSignIn(providerSelect.value, true).catch(reportError);
  });
  document.getElementById('wallet-disconnect').addEventListener('click', () => {
    document.getElementById('wallet-menu').open = false;
    wallet.disconnect().catch(reportError);
  });
  document.getElementById('wallet-copy').addEventListener('click', () => {
    if (wallet.address) navigator.clipboard.writeText(wallet.address).catch(reportError);
    document.getElementById('wallet-menu').open = false;
  });
  document.getElementById('wallet-chat-action').addEventListener('click', async () => {
    try {
      if (!wallet.providers.size) { wallet.surface.dispatchEvent(new Event('eip6963:requestProvider')); providers(); return; }
      if (!wallet.ready) await wallet.connectAndSignIn(providerSelect.value);
      else await history.create();
    } catch (error) { reportError(error); }
  });
  wallet.discover();
  providers();
  update();
  await wallet.restore();
  await wallet.retryReports();
}

// Bootstrap
async function bootstrap() {
  const header = document.querySelector('.app-header');
  const measureHeader = () => document.documentElement.style.setProperty('--app-header-height', `${header.getBoundingClientRect().height}px`);
  new ResizeObserver(measureHeader).observe(header);
  measureHeader();
  let userScrolling = false;
  let scrollTimer;
  const markUserScroll = () => {
    userScrolling = true;
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => { userScrolling = false; }, 300);
  };
  for (const event of ['wheel', 'touchmove', 'pointerdown']) {
    elements.chatHistory.addEventListener(event, markUserScroll, { passive: true });
  }
  elements.chatHistory.addEventListener('keydown', event => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) markUserScroll();
  });
  elements.chatHistory.addEventListener('scroll', () => {
    if (!userScrolling) return;
    state.followLatest = elements.chatHistory.scrollHeight - elements.chatHistory.scrollTop - elements.chatHistory.clientHeight < 48;
    markUserScroll();
  });
  new ResizeObserver(() => {
    if (state.followLatest) elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
  }).observe(elements.chatHistory);
  await initializeI18n();
  // Apply persisted theme immediately
  applyTheme(state.theme);

  // Initialize icons and i18n
  initIcons();
  updateLanguageUI(state.language);
  setupEventListeners();
  greetUser();

  try {
    const health = await api('/health');
    await initializeWalletMode(health);
  } catch (error) {
    elements.btnSendMessage.disabled = true;
    appendMessage('agent', error.message);
    return;
  }

  await Promise.all([
    loadNetworkStatus(),
    loadWalletInfo(),
    loadPolicies(),
  ]);

  // Periodic refresh every 20s
  setInterval(() => {
    if (!state.isProcessing) {
      loadNetworkStatus();
      loadWalletInfo();
      if (state.walletMode) state.historyView.refreshTransactions().catch(() => {});
    }
  }, 20000);
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', bootstrap, { once: true });
} else {
  bootstrap();
}
