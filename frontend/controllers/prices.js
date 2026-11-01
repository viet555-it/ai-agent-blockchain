/** Price Controller: coordinates price data fetching, alerts, and view updates. */

import { api } from '../api.js';

export function createPriceController(state, elements, view) {
  let activeTimeframe = '24h';
  const alertedIds = new Set();

  async function loadCurrentPrice() {
    try {
      const data = await api('/prices/current');
      view.renderCurrentPrice(data);

      if (data.alerts_triggered && Array.isArray(data.alerts_triggered)) {
        for (const alert of data.alerts_triggered) {
          if (!alertedIds.has(alert.id)) {
            alertedIds.add(alert.id);
            view.showAlertToast(alert);
          }
        }
      }
      return data;
    } catch (err) {
      console.error('Failed to load current price:', err);
      view.renderCurrentPrice({ price_usd: null, error: err.message });
    }
  }

  async function loadPriceHistory(timeframe = activeTimeframe) {
    activeTimeframe = timeframe;
    try {
      const data = await api(`/prices/history?timeframe=${encodeURIComponent(timeframe)}`);
      view.renderMainChart(data);
      return data;
    } catch (err) {
      console.error('Failed to load price history:', err);
    }
  }

  async function loadComparison() {
    try {
      const data = await api('/prices/comparison');
      view.renderComparison(data);
      return data;
    } catch (err) {
      console.error('Failed to load comparison data:', err);
      view.renderComparison({ rates: {} });
    }
  }

  async function loadChainlinkPrice() {
    try {
      return await api('/prices/chainlink');
    } catch (err) {
      console.error('Failed to load Chainlink price:', err);
      return null;
    }
  }

  async function loadAlerts() {
    try {
      const alerts = await api('/prices/alerts');
      view.renderAlerts(alerts, removeAlert);
      return alerts;
    } catch (err) {
      console.error('Failed to load alerts:', err);
    }
  }

  async function addAlert(direction, threshold) {
    try {
      await api('/prices/alerts', {
        method: 'POST',
        body: { direction, threshold: Number(threshold) },
      });
      await loadAlerts();
    } catch (err) {
      console.error('Failed to add price alert:', err);
    }
  }

  async function removeAlert(alertId) {
    try {
      await api(`/prices/alerts/${encodeURIComponent(alertId)}`, {
        method: 'DELETE',
      });
      alertedIds.delete(alertId);
      await loadAlerts();
    } catch (err) {
      console.error('Failed to remove price alert:', err);
    }
  }

  function bindEvents() {
    // 3 Timeframe buttons
    document.querySelectorAll('.price-timeframe-btn[data-tf]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.price-timeframe-btn[data-tf]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tf = btn.getAttribute('data-tf');
        loadPriceHistory(tf);
      });
    });

    // Alert form submit
    if (elements.priceAlertForm) {
      elements.priceAlertForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const dir = elements.priceAlertDirection?.value || 'above';
        const val = elements.priceAlertThreshold?.value;
        if (val) {
          addAlert(dir, val);
          elements.priceAlertThreshold.value = '';
        }
      });
    }
  }

  return {
    loadCurrentPrice,
    loadPriceHistory,
    loadComparison,
    loadChainlinkPrice,
    loadAlerts,
    addAlert,
    removeAlert,
    bindEvents,
    getActiveTimeframe: () => activeTimeframe,
  };
}

