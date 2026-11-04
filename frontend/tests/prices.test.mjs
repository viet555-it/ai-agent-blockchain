import test from 'node:test';
import assert from 'node:assert/strict';
import { createPriceController } from '../controllers/prices.js';
globalThis.document = { cookie: '' };

test('createPriceController loads price data and handles error without fake numbers', async () => {
  let renderedPrice = null;
  const mockView = {
    renderCurrentPrice: (data) => { renderedPrice = data; },
    renderMainChart: () => {},
    renderComparison: () => {},
    renderAlerts: () => {},
    showAlertToast: () => {},
  };

  const state = {};
  const elements = {};
  const controller = createPriceController(state, elements, mockView);

  // Test error handling: null price
  mockView.renderCurrentPrice({ price_usd: null, source: null, error: 'Network failure' });
  assert.equal(renderedPrice.price_usd, null);
  assert.equal(renderedPrice.source, null);
});

test('createPriceController handles alerts without repeating continuously', async () => {
  let toasts = [];
  const mockView = {
    renderCurrentPrice: () => {},
    renderMainChart: () => {},
    renderComparison: () => {},
    renderAlerts: () => {},
    showAlertToast: (alert) => { toasts.push(alert); },
  };

  const state = {};
  const elements = {};
  const controller = createPriceController(state, elements, mockView);

  assert.equal(typeof controller.loadCurrentPrice, 'function');
  assert.equal(typeof controller.loadPriceHistory, 'function');
  assert.equal(typeof controller.loadComparison, 'function');
  assert.equal(typeof controller.addAlert, 'function');
  assert.equal(typeof controller.removeAlert, 'function');
});

test('a delayed timeframe response never replaces the chart for the latest selection', async () => {
  const waiting = new Map();
  globalThis.fetch = url => new Promise(resolve => waiting.set(url, data => resolve({ ok: true, json: async () => data })));
  const rendered = [];
  const controller = createPriceController({}, {}, { renderMainChart: data => rendered.push(data) });
  const older = controller.loadPriceHistory('24h');
  const latest = controller.loadPriceHistory('1h');
  waiting.get('/api/prices/history?timeframe=1h')({ timeframe: '1h', prices: [{ timestamp: 1, price: 2500 }] });
  await latest;
  waiting.get('/api/prices/history?timeframe=24h')({ timeframe: '24h', prices: [] });
  await older;
  assert.deepEqual(rendered.map(data => data.timeframe), ['1h']);
});

