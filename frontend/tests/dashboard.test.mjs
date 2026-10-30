import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.localStorage = { getItem: () => 'en' };
globalThis.document = { cookie: 'ati_csrf=test-token' };
const { createAssetsController } = await import('../controllers/assets.js');
const { createChatController } = await import('../controllers/chat.js');
const { createApprovalController } = await import('../controllers/approvals.js');
const { dashboardApi } = await import('../api.js');

test('a wallet balance arriving after an account change is never rendered', async () => {
  let generation = 1;
  let finish;
  const rendered = [];
  const state = {
    walletMode: true,
    walletController: { address: 'wallet-a', generation, current: expected => generation === expected },
  };
  const controller = createAssetsController(state, { renderWallet: value => rendered.push(value) }, {
    walletInfo: () => new Promise(resolve => { finish = resolve; }),
  });
  const loading = controller.loadWalletInfo();
  generation++;
  finish({ address: 'wallet-a', native_balance: '12' });
  await loading;
  assert.deepEqual(rendered, []);
});

test('a chat response from the previous conversation does not update the new view', async () => {
  let finish;
  const rendered = [];
  const state = {
    walletMode: true,
    isProcessing: false,
    historyView: { epoch: 1, readOnly: false },
    walletController: {
      ready: true, generation: 1, conversation: 'chat-a',
      context: { id: 'context-a', generation: 1 }, current: expected => expected === 1,
    },
  };
  const controller = createChatController(state, {
    btnSendMessage: {}, chatInput: {},
  }, {
    appendMessage: (...args) => rendered.push(args),
    showTypingIndicator() {},
    removeTypingIndicator: () => rendered.push('remove typing'),
    renderTimeline: () => rendered.push('timeline'),
    openApprovalModal: () => rendered.push('approval'),
    renderCitation: () => '',
    renderWalletGate: () => rendered.push('gate'),
  }, { turn: () => new Promise(resolve => { finish = resolve; }) });
  const sending = controller.handleSendMessage('private message for chat A');
  state.walletController.conversation = 'chat-b';
  state.historyView.epoch++;
  finish({ response: { reply: 'old response', timeline: [] } });
  await sending;
  assert.deepEqual(rendered, [['user', 'private message for chat A']]);
});

test('legacy receipt polling reads status without resubmitting approval', async () => {
  const calls = [];
  const state = {
    walletMode: false, sessionId: 'session-a', activeApprovalParameters: { amount: '1' },
    pendingApproval: { approval_id: 'approval-a' },
  };
  const elements = {
    btnModalApprove: { querySelector: () => ({}) }, btnModalReject: {},
  };
  const controller = createApprovalController(state, elements, {
    closeApprovalModal: () => { state.pendingApproval = null; },
    appendMessage() {}, loadWalletInfo() {}, loadNetworkStatus() {},
  }, {
    reviewApproval: async body => { calls.push(['review', body]); return { status: 'PENDING' }; },
    approvalStatus: async (...args) => { calls.push(['status', ...args]); return { status: 'CONFIRMED', tx_hash: '0x123' }; },
  });
  await controller.submitApprovalAction('APPROVE');
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], 'review');
  assert.equal(calls[0][1].session_id, 'session-a');
  assert.deepEqual(calls[1], ['status', 'approval-a', 'session-a']);
  assert.equal(state.pendingApproval, null);
});

test('approval status requests retain the session binding header', async () => {
  let request;
  globalThis.fetch = async (path, options) => {
    request = { path, ...options };
    return { ok: true, json: async () => ({ status: 'PENDING' }) };
  };
  await dashboardApi.approvalStatus('approval/a', 'session-a');
  assert.equal(request.path, '/api/approval/approval%2Fa');
  assert.equal(request.method, 'GET');
  assert.equal(request.headers['X-Session-ID'], 'session-a');
  assert.equal(request.headers['X-CSRF-Token'], 'test-token');
});
