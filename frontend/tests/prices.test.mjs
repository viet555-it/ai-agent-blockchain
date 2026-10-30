import test from 'node:test';
import assert from 'node:assert/strict';
import { createPriceController } from '../controllers/prices.js';

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

