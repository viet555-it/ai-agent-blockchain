import test from 'node:test';
import assert from 'node:assert/strict';
import { WalletController, sameAddress } from '../wallet.js';
import { transactionForProvider, displayDecimal } from '../api.js';

globalThis.BroadcastChannel = undefined;
globalThis.document = { cookie: 'ati_csrf=test-token' };
globalThis.sessionStorage = {
  setItem(key, value) { this[key] = value; },
  getItem(key) { return this[key] ?? null; },
  removeItem(key) { delete this[key]; },
};
const A = '0x' + 'a1'.repeat(20);
const B = '0x' + 'b2'.repeat(20);

function provider() {
  return {
    address: A, sends: 0, listeners: new Map(),
    on(name, listener) { const values = this.listeners.get(name) || new Set(); values.add(listener); this.listeners.set(name, values); },
    removeListener(name, listener) { this.listeners.get(name)?.delete(listener); },
    async request({ method }) {
      if (method === 'eth_accounts') return [this.address];
      if (method === 'eth_chainId') return '0x7a69';
      if (method === 'eth_sendTransaction') { this.sends++; return '0x' + '11'.repeat(32); }
      throw new Error(method);
    },
  };
}

test('transaction conversion preserves exact uint256 amounts above JS Number precision', () => {
  const value = '115792089237316195423570985008687907853269984665640564039457584007913129639935';
  const converted = transactionForProvider({ from: A, value, gas: '21000', nonce: '0', chainId: '31337' });
  assert.equal(BigInt(converted.value).toString(), value);
  assert.equal(converted.gas, '0x5208');
  assert.equal(converted.from, A);
  assert.ok(sameAddress(A, A.toUpperCase()));
  assert.equal(displayDecimal('9999.998698071654296875'), '9999.998698…');
});

test('account selection invalidates context immediately and ignores an old generation', async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ status: 'REVOKED' }) });
  const wallet = new WalletController(31337);
  wallet.address = A; wallet.chainId = 31337; wallet.context = { id: 'context-a' }; wallet.status = 'ready';
  const generation = wallet.generation;
  wallet.select(B, 31337);
  assert.equal(wallet.context, null);
  assert.equal(wallet.ready, false);
  assert.equal(wallet.address, B);
  assert.equal(wallet.current(generation), false);
  await wallet.authRevocation;
});

test('changing provider removes listeners from the previous provider', () => {
  const first = provider(), second = provider();
  const wallet = new WalletController(31337);
  wallet.attach(first);
  wallet.attach(second);
  assert.equal(first.listeners.get('accountsChanged').size, 0);
  assert.equal(second.listeners.get('accountsChanged').size, 1);
});

test('account change during authorize never sends from the new wallet', async () => {
  let resolveAuthorize;
  const waiting = new Promise(resolve => { resolveAuthorize = resolve; });
  globalThis.fetch = async path => {
    if (path.endsWith('/authorize')) await waiting;
    return { ok: true, json: async () => ({ submission_id: 'attempt', report_token: 'report-token', transaction: { from: A, to: B, value: '1' } }) };
  };
  const injected = provider();
  const wallet = new WalletController(31337);
  wallet.attach(injected);
  wallet.address = A; wallet.chainId = 31337; wallet.context = { id: 'a', generation: 1 }; wallet.status = 'ready';
  const pending = wallet.submit({ approval_id: 'proposal', parameter_hash: 'hash' }, 'APPROVE');
  await new Promise(resolve => setImmediate(resolve));
  injected.address = B;
  wallet.select(B, 31337);
  resolveAuthorize();
  await assert.rejects(pending, /changed/);
  assert.equal(injected.sends, 0);
});

test('a second approval click cannot create another wallet send request', async () => {
  let resolveAuthorize;
  const waiting = new Promise(resolve => { resolveAuthorize = resolve; });
  globalThis.fetch = async path => {
    if (path.endsWith('/authorize')) await waiting;
    return { ok: true, json: async () => ({ submission_id: 'attempt', report_token: 'report-token', transaction: { from: A, to: B, value: '1' } }) };
  };
  const injected = provider();
  const wallet = new WalletController(31337);
  wallet.attach(injected);
  wallet.address = A; wallet.chainId = 31337; wallet.context = { id: 'a', generation: 1 }; wallet.status = 'ready';
  const approval = { approval_id: 'proposal', parameter_hash: 'hash' };
  const pending = wallet.submit(approval, 'APPROVE');
  await assert.rejects(wallet.submit(approval, 'APPROVE'));
  resolveAuthorize();
  await pending;
  assert.equal(injected.sends, 1);
});
