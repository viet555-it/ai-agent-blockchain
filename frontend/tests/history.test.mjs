import test from 'node:test';
import assert from 'node:assert/strict';

globalThis.localStorage = { getItem: () => 'en' };
globalThis.document = { getElementById: () => ({ addEventListener() {} }) };
const { HistoryView } = await import('../history.js');

test('a conversation from an old deployment never becomes the default active chat', async () => {
  const wallet = { ready: true, generation: 1, current: generation => generation === 1, context: { deployment_id: 'new-chain' } };
  const view = new HistoryView(wallet, { error() {} });
  view.list = async () => { view.conversations = [{ id: 'old-chat', deployment_id: 'old-chain' }]; };
  let created = 0, opened = null;
  view.create = async () => { created++; };
  view.open = async id => { opened = id; };
  view.refreshTransactions = view.refreshAudit = async () => {};
  await view.initialize();
  assert.equal(created, 1);
  assert.equal(opened, null);
});

test('verified receipts notify only their own chat, once, without treating reverted or mismatched transfers as success', () => {
  const shown = [];
  const view = new HistoryView({ conversation: 'chat-a' }, { append: (...message) => shown.push(message), error() {} });
  const pending = {
    id: 'attempt', conversation_id: 'chat-a', tx_hash: '0x' + '12'.repeat(32),
    status: 'SUBMITTED', verification_status: 'UNVERIFIED', receipt_status: null,
    parameters: { amount: '10', token_symbol: 'AGNT', recipient: '0xrecipient', chain_id: 11155111 },
  };
  view.transactionOutcomes.set(pending.id, pending);
  view.renderTransactionOutcomes();
  assert.equal(shown.length, 0);
  view.transactionOutcomes.set(pending.id, { ...pending, status: 'MINED_SUCCESS', verification_status: 'MATCHED', receipt_status: 1 });
  view.renderTransactionOutcomes();
  view.renderTransactionOutcomes();
  assert.equal(shown.length, 1);
  assert.match(shown[0][1], /modal.confirmedMsg/);
  assert.match(shown[0][1], /10 AGNT/);
  assert.match(shown[0][1], /sepolia.etherscan.io/);
  view.transactionOutcomes.set('mismatch', { ...pending, id: 'mismatch', status: 'FINALIZED', verification_status: 'MISMATCHED', receipt_status: 1 });
  view.transactionOutcomes.set('other-chat', { ...pending, id: 'other-chat', conversation_id: 'chat-b', status: 'FINALIZED', verification_status: 'MATCHED', receipt_status: 1 });
  view.transactionOutcomes.set('reverted', { ...pending, id: 'reverted', status: 'FINALIZED', verification_status: 'MATCHED', receipt_status: 0 });
  view.renderTransactionOutcomes();
  assert.equal(shown.length, 2);
  assert.match(shown[1][1], /modal.revertedMsg/);
  view.displayedOutcomes.clear(); // Loading the saved conversation rebuilds its outcomes.
  shown.length = 0;
  view.renderTransactionOutcomes();
  assert.equal(shown.length, 2);
});
