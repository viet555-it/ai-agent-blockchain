import { icons } from '../icons.js';
import { t } from '../i18n.js';
import { escapeHtml, formatMarkdown } from './format.js';
import { api } from '../api.js';

function renderCitation(data) {
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

  return ragCitationHtml;
}

export function createChatView(state, elements, priceChartView = null) {
  function appendMessage(sender, text, extraHtml = '') {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${sender}`;

    const avatar = document.createElement('div');
    avatar.className = `avatar ${sender === 'user' ? 'user-avatar' : 'agent-avatar'}`;
    avatar.innerHTML = sender === 'user' ? icons.user : icons.bot;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    let cleanText = text || '';
    let chartTf = null;

    if (sender === 'agent' && cleanText.includes('[CHART:ETH:')) {
      const match = cleanText.match(/\[CHART:ETH:(1h|24h|7d)\]/i);
      if (match) chartTf = match[1].toLowerCase();
      cleanText = cleanText.replace(/\[CHART:ETH:[^\]]+\]/g, '').trim();
    }

    bubble.innerHTML = `<div>${formatMarkdown(cleanText)}</div>${extraHtml}`;

    if (chartTf && priceChartView && priceChartView.createChatChartComponent) {
      const chartPlaceholder = document.createElement('div');
      chartPlaceholder.style.minHeight = '60px';
      chartPlaceholder.style.display = 'flex';
      chartPlaceholder.style.alignItems = 'center';
      chartPlaceholder.style.justifyContent = 'center';
      chartPlaceholder.style.fontSize = 'var(--text-xs)';
      chartPlaceholder.style.color = 'var(--text-dim)';
      chartPlaceholder.textContent = 'Đang tải biểu đồ...';
      bubble.appendChild(chartPlaceholder);

      api(`/prices/history?timeframe=${encodeURIComponent(chartTf)}`)
        .then(historyData => {
          chartPlaceholder.remove();
          const chartElement = priceChartView.createChatChartComponent(historyData);
          bubble.appendChild(chartElement);
          elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
        })
        .catch(err => {
          chartPlaceholder.textContent = `❌ Không thể tải biểu đồ: ${err.message}`;
        });
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);

    elements.chatHistory.appendChild(msgDiv);
    state.followLatest = true;
    elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
    return bubble;
  }

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

  return { appendMessage, showTypingIndicator, removeTypingIndicator, renderCitation };
}
