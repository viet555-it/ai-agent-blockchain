/** UI View for Price Tracking, 3-Timeframe Chart, Comparison, and In-Chat Component. */

import { icons } from '../icons.js';
import { t } from '../i18n.js';
import { escapeHtml } from './format.js';

export function createPriceChartView(state, elements) {
  let mainChartInstance = null;
  const chatChartInstances = new Map();

  function formatTime(timestamp, timeframe) {
    const d = new Date(timestamp * 1000);
    if (timeframe === '1h') {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    if (timeframe === '24h') {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:00`;
  }

  function initChart(canvas, prices, timeframe = '24h', isMini = false) {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js is not loaded.');
      return null;
    }

    const ctx = canvas.getContext('2d');
    const labels = prices.map(p => formatTime(p.timestamp, timeframe));
    const dataPoints = prices.map(p => p.price);

    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
    const primaryColor = isDark ? '#f59e0b' : '#d97706';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';
    const textColor = isDark ? '#94a3b8' : '#64748b';

    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 160);
    gradient.addColorStop(0, isDark ? 'rgba(245, 158, 11, 0.25)' : 'rgba(217, 119, 6, 0.2)');
    gradient.addColorStop(1, 'rgba(245, 158, 11, 0.0)');

    return new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data: dataPoints,
          borderColor: primaryColor,
          borderWidth: isMini ? 1.5 : 2,
          backgroundColor: gradient,
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: isMini ? 2 : 4,
          pointHoverBackgroundColor: primaryColor,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            mode: 'index',
            intersect: false,
            displayColors: false,
            callbacks: {
              label: (context) => `$${Number(context.parsed.y).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
            },
          },
        },
        scales: {
          x: {
            display: !isMini,
            grid: { display: false },
            ticks: {
              color: textColor,
              font: { size: 9 },
              maxTicksLimit: 6,
            },
          },
          y: {
            display: !isMini,
            grid: { color: gridColor },
            ticks: {
              color: textColor,
              font: { size: 9 },
              callback: (val) => `$${val}`,
              maxTicksLimit: 4,
            },
          },
        },
        interaction: {
          mode: 'nearest',
          axis: 'x',
          intersect: false,
        },
      },
    });
  }

  function renderMainChart(historyData) {
    if (!elements.priceChartCanvas) return;
    if (mainChartInstance) {
      mainChartInstance.destroy();
      mainChartInstance = null;
    }

    const prices = historyData?.prices || [];
    const tf = historyData?.timeframe || '24h';
    mainChartInstance = initChart(elements.priceChartCanvas, prices, tf, false);
  }

  function renderCurrentPrice(priceData) {
    if (!elements.priceCurrentValue) return;

    if (priceData.price_usd !== null && priceData.price_usd !== undefined) {
      elements.priceCurrentValue.textContent = `$${Number(priceData.price_usd).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;

      const chg = priceData.change_24h_pct;
      if (elements.priceChangeBadge) {
        if (chg !== null && chg !== undefined) {
          const isPos = Number(chg) >= 0;
          elements.priceChangeBadge.className = `price-change-pill ${isPos ? 'positive' : 'negative'}`;
          elements.priceChangeBadge.textContent = `${isPos ? '+' : ''}${chg}%`;
          elements.priceChangeBadge.style.display = 'inline-flex';
        } else {
          elements.priceChangeBadge.style.display = 'none';
        }
      }

      if (elements.priceSource) {
        elements.priceSource.textContent = priceData.source || 'CoinGecko';
        elements.priceSource.className = `price-source-badge ${priceData.source === 'chainlink_sepolia' ? 'chainlink' : ''}`;
      }

      if (elements.priceUpdatedAt && priceData.updated_at) {
        const d = new Date(priceData.updated_at);
        elements.priceUpdatedAt.textContent = `${t('prices.updatedAt', { time: d.toLocaleTimeString() })}`;
      }
    } else {
      elements.priceCurrentValue.textContent = '--';
      if (elements.priceChangeBadge) elements.priceChangeBadge.style.display = 'none';
      if (elements.priceSource) elements.priceSource.textContent = 'API Error';
      if (elements.priceUpdatedAt) elements.priceUpdatedAt.textContent = t('prices.apiError');
    }
  }

  function renderComparison(compData) {
    if (!elements.priceComparisonBody) return;
    const rates = compData?.rates || {};
    if (Object.keys(rates).length === 0) {
      elements.priceComparisonBody.innerHTML = `<tr><td colspan="2" style="color:var(--text-dim); text-align:center;">${t('prices.apiError')}</td></tr>`;
      return;
    }

    const items = [
      { key: 'USD', val: rates.usd ? `$${Number(rates.usd).toLocaleString()}` : '--' },
      { key: 'EUR', val: rates.eur ? `€${Number(rates.eur).toLocaleString()}` : '--' },
      { key: 'JPY', val: rates.jpy ? `¥${Number(rates.jpy).toLocaleString()}` : '--' },
      { key: 'BTC', val: rates.btc ? `₿ ${Number(rates.btc).toFixed(5)}` : '--' },
    ];

    elements.priceComparisonBody.innerHTML = items.map(item => `
      <tr>
        <td>1 ETH / ${item.key}</td>
        <td class="rate">${item.val}</td>
      </tr>
    `).join('');
  }

  function renderAlerts(alerts, onRemove) {
    if (!elements.priceAlertsList) return;
    if (!alerts || alerts.length === 0) {
      elements.priceAlertsList.innerHTML = `<div style="font-size:var(--text-xs); color:var(--text-dim); padding:0.25rem 0;">${t('prices.noAlerts')}</div>`;
      return;
    }

    elements.priceAlertsList.innerHTML = alerts.map(a => `
      <div class="price-alert-item ${a.triggered ? 'triggered' : ''}">
        <span>${a.direction === 'above' ? '▲' : '▼'} ${a.pair} ${a.direction === 'above' ? t('prices.above') : t('prices.below')} $${Number(a.threshold).toLocaleString()}</span>
        <button type="button" class="price-alert-del-btn" data-id="${escapeHtml(a.id)}" title="Delete alert">×</button>
      </div>
    `).join('');

    elements.priceAlertsList.querySelectorAll('.price-alert-del-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-id');
        if (id && onRemove) onRemove(id);
      });
    });
  }

  function showAlertToast(alert) {
    const toast = document.createElement('div');
    toast.className = 'price-alert-toast';
    toast.innerHTML = `
      <span style="font-size:1.2rem;">⚡</span>
      <div>
        <div style="font-weight:600; font-size:var(--text-sm); color:var(--primary);">
          ${t('prices.alerts')}
        </div>
        <div style="font-size:var(--text-xs); color:var(--text-main);">
          ${t('prices.alertTriggered', { direction: alert.direction, threshold: alert.threshold })}
        </div>
      </div>
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.5s ease';
      setTimeout(() => toast.remove(), 500);
    }, 5000);
  }

  function createChatChartComponent(historyData, options = {}) {
    const card = document.createElement('div');
    card.className = 'chat-price-chart-card';

    const tf = historyData?.timeframe || '24h';
    const cardId = `chat-chart-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

    card.innerHTML = `
      <div class="chat-price-chart-header">
        <div class="chat-price-chart-title">
          <span>${icons.analytics || '📈'}</span>
          <span>ETH / USD (${tf.toUpperCase()})</span>
        </div>
        <span class="price-source-badge">${historyData?.source || 'CoinGecko'}</span>
      </div>
      <div class="chat-price-chart-canvas-wrap">
        <canvas id="${cardId}"></canvas>
      </div>
    `;

    setTimeout(() => {
      const canvas = document.getElementById(cardId);
      if (canvas && historyData?.prices) {
        const instance = initChart(canvas, historyData.prices, tf, false);
        chatChartInstances.set(cardId, instance);
      }
    }, 100);

    return card;
  }

  return {
    renderMainChart,
    renderCurrentPrice,
    renderComparison,
    renderAlerts,
    showAlertToast,
    createChatChartComponent,
  };
}

