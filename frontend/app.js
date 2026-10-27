/**
 * AI Agent Blockchain Dashboard Application Logic
 * Integrates with FastAPI backend, Policy Engine, and Web3 Services.
 */
import { icons } from './icons.js';

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
 * Initialize icons and event handlers
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
}

/**
 * Shorten an Ethereum address for display (0x1234...abcd)
 */
function shortenAddress(addr) {
  if (!addr || addr.length < 10) return addr || '0x...';
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
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
    elements.modalNetwork.textContent = `${data.name} (${data.chain_id})`;
    document.getElementById('contract-network-label').textContent = `Smart Contract (${data.name})`;
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
      elements.valBaseFee.textContent = `Base fee: ${baseGwei} Gwei`;
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
  try {
    const res = await fetch(`${API_BASE}/api/wallet/info`);
    if (!res.ok) throw new Error('Wallet info unreachable');
    const data = await res.json();
    state.wallet = data;

    elements.headerWalletAddress.textContent = shortenAddress(data.address);
    elements.valNativeBalance.textContent = parseFloat(data.native_balance || '0').toFixed(4);
    elements.valNativeSymbol.textContent = data.native_symbol || 'ETH';
    elements.valTokenBalance.textContent = parseFloat(data.token_balance || '0').toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
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
 * Format markdown text (bold, code block, links) to safe HTML
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
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="info-mono" style="background: rgba(0,0,0,0.3); padding: 0.15rem 0.35rem; border-radius: 4px;">$1</code>');
  // Block quotes
  formatted = formatted.replace(/^>\s*(.*?)$/gm, '<blockquote style="border-left: 3px solid var(--secondary); padding-left: 0.75rem; color: var(--text-muted); margin: 0.5rem 0;">$1</blockquote>');
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
  elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
  return bubble;
}

/**
 * Render typing indicator
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
    <div style="display: flex; gap: 0.3rem; align-items: center; padding: 0.3rem 0;">
      <span class="pulse-dot" style="width: 6px; height: 6px;"></span>
      <span class="pulse-dot" style="width: 6px; height: 6px; animation-delay: 200ms;"></span>
      <span class="pulse-dot" style="width: 6px; height: 6px; animation-delay: 400ms;"></span>
      <span style="font-size: 0.8rem; color: var(--text-dim); margin-left: 0.4rem;">Analyzing intent & verifying policies...</span>
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
 * Render 9-Step Agent Workflow Timeline
 */
function renderTimeline(timelineSteps) {
  if (!timelineSteps || timelineSteps.length === 0) {
    elements.timelineEmptyState.style.display = 'block';
    elements.timelineList.style.display = 'none';
    elements.timelineStepCount.textContent = '0 / 9 Steps';
    return;
  }

  elements.timelineEmptyState.style.display = 'none';
  elements.timelineList.style.display = 'flex';
  elements.timelineList.innerHTML = '';
  elements.timelineStepCount.textContent = `${timelineSteps.length} / 9 Steps`;

  timelineSteps.forEach((step, idx) => {
    const item = document.createElement('div');
    const statusClass = step.status.toLowerCase().replace('_', '-');
    item.className = `timeline-item ${statusClass}`;

    const stepId = `step-details-${idx}`;

    item.innerHTML = `
      <div class="step-num-badge">${step.step_number}</div>
      <div class="step-content">
        <div class="step-header">
          <span class="step-name">${step.name}</span>
          <span class="step-badge ${statusClass}">${step.status}</span>
        </div>
        ${step.duration_ms ? `<div class="step-duration">${step.duration_ms} ms</div>` : ''}
        ${step.tool_name ? `<div style="font-size: 0.75rem; color: var(--primary);">Tool: <strong>${escapeHtml(step.tool_name)}</strong></div>` : ''}
        
        ${step.result || step.sanitized_parameters || step.error ? `
          <button type="button" class="step-details-toggle" data-target="${stepId}">
            <span>${icons.chevronDown}</span>
            <span>View Payload</span>
          </button>
          <div class="step-details-box" id="${stepId}">
            ${escapeHtml(JSON.stringify(step.result || step.sanitized_parameters || { error: step.error }, null, 2))}
          </div>
        ` : ''}
      </div>
    `;

    elements.timelineList.appendChild(item);
  });

  // Attach toggle listeners
  elements.timelineList.querySelectorAll('.step-details-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const box = document.getElementById(targetId);
      if (box) {
        box.classList.toggle('open');
        btn.querySelector('span:first-child').innerHTML = box.classList.contains('open') 
          ? icons.chevronUp 
          : icons.chevronDown;
      }
    });
  });
}

/**
 * Open Transaction Review and Approval Modal
 */
function openApprovalModal(approval, guardrailResult) {
  state.pendingApproval = approval;
  state.activeApprovalParameters = approval.parameters;

  elements.modalOpName.textContent = approval.operation;
  elements.modalRecipient.textContent = approval.parameters.recipient || 'N/A';
  elements.modalAmount.textContent = `${approval.parameters.amount || '0'} ${approval.parameters.token_symbol || 'AGNT'}`;
  
  if (guardrailResult && guardrailResult.simulation_result) {
    const sim = guardrailResult.simulation_result;
    elements.modalSimResult.textContent = sim.isValid 
      ? `Valid · chain ${approval.parameters.chain_id ?? '?'} · gas fee cap ${sim.max_fee_wei ?? '?'} wei`
      : `Revert Warning: ${sim.reason}`;
    elements.modalSimResult.style.color = sim.isValid ? 'var(--success)' : 'var(--danger)';
  } else {
    elements.modalSimResult.textContent = 'Pre-flight check passed.';
    elements.modalSimResult.style.color = 'var(--success)';
  }

  elements.btnModalApprove.disabled = false;
  elements.btnModalReject.disabled = false;
  elements.btnModalApprove.querySelector('span:first-child').textContent = 'CONFIRM & EXECUTE';
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

  const approvalId = state.pendingApproval.approval_id;
  const params = state.activeApprovalParameters;

  elements.btnModalApprove.disabled = true;
  elements.btnModalReject.disabled = true;
  elements.btnModalApprove.querySelector('span:first-child').textContent = 'Processing on Chain...';

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
        ? `<div style="margin-top: 0.5rem;"><a href="${data.explorer_url}" target="_blank" rel="noopener noreferrer" style="color: var(--primary); text-decoration: underline; font-weight: 600;">View Transaction on Etherscan &rarr;</a></div>` 
        : '';
      
      const descriptions = {
        CONFIRMED: 'Giao dịch đã được xác nhận thành công trên blockchain.',
        REVERTED: 'Giao dịch đã revert. Không thể coi là thành công.',
        PENDING: 'Đã gửi giao dịch, đang chờ receipt. Không gửi lại yêu cầu.',
        UNKNOWN: 'Chưa xác định kết quả giao dịch. Cần kiểm tra nonce/chain; không gửi lại.',
      };
      const description = descriptions[data.status] || `Trạng thái: ${data.status}`;
      appendMessage('agent', `${description}\n- **Tx Hash:** \`${data.tx_hash || 'chưa xác định'}\``, explorerLink);
      // Refresh wallet balances
      loadWalletInfo();
      loadNetworkStatus();
    } else {
      appendMessage('agent', 'Transaction was rejected by your request. No funds were transferred.');
    }
  } catch (err) {
    alert(`Approval Error: ${err.message}`);
    elements.btnModalApprove.disabled = false;
    elements.btnModalReject.disabled = false;
    elements.btnModalApprove.querySelector('span:first-child').textContent = 'CONFIRM & EXECUTE';
  }
}

/**
 * Handle sending a chat message
 */
async function handleSendMessage(query) {
  if (!query || !query.trim() || state.isProcessing) return;

  state.isProcessing = true;
  elements.btnSendMessage.disabled = true;
  elements.chatInput.value = '';

  // Append user message
  appendMessage('user', query);
  showTypingIndicator();

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: query,
        wallet_address: state.wallet ? state.wallet.address : null,
        session_id: state.sessionId,
      }),
    });

    removeTypingIndicator();

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to communicate with AI Agent');
    }

    const data = await res.json();

    // Extra RAG citation card if returned
    let ragCitationHtml = '';
    if (data.rag_result && data.rag_result.has_relevant_context && data.rag_result.documents.length > 0) {
      const doc = data.rag_result.documents[0];
      ragCitationHtml = `
        <div class="rag-citation">
          <div class="rag-header">
            <span>${icons.bookOpen} Knowledge Retrieval (RAG)</span>
            <span>Similarity: ${Number(doc.score).toFixed(3)}</span>
          </div>
          <div class="rag-body">${escapeHtml(doc.excerpt)}</div>
          <div class="rag-source">Source: ${escapeHtml(doc.title)} (${escapeHtml(doc.source_file)})</div>
        </div>
      `;
    }

    // Append Agent reply
    appendMessage('agent', data.reply, ragCitationHtml);

    // Update Activity Timeline
    renderTimeline(data.timeline);

    // If approval is required, trigger approval modal
    if (data.requires_approval && data.guardrail_result && data.guardrail_result.pending_approval) {
      openApprovalModal(data.guardrail_result.pending_approval, data.guardrail_result);
    }

  } catch (err) {
    removeTypingIndicator();
    appendMessage('agent', `❌ An error occurred: ${err.message}`);
    console.error('Chat error:', err);
  } finally {
    state.isProcessing = false;
    elements.btnSendMessage.disabled = false;
    elements.chatInput.focus();
  }
}

/**
 * Setup Event Listeners
 */
function setupEventListeners() {
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
      setTimeout(() => { elements.btnCopyHeaderWallet.innerHTML = original; }, 1500);
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
  appendMessage(
    'agent',
    `**Welcome to AI Agent with Blockchain Tools!**\n\n` +
    `I am your autonomous on-chain assistant secured by the **Guardrail & Policy Engine**.\n\n` +
    `You can query balances, check token info, simulate dry-runs, or submit transfer requests. ` +
    `All write operations will be validated against safety policies and presented for your explicit approval.`
  );
}

// Bootstrap
window.addEventListener('DOMContentLoaded', async () => {
  initIcons();
  setupEventListeners();
  greetUser();

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
    }
  }, 20000);
});
