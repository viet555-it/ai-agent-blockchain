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
