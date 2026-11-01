/** Same-origin authenticated requests. Session credentials never enter localStorage. */
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || `HTTP ${status}`);
    this.status = status;
    this.code = detail?.code;
  }
}

export async function api(path, { method = 'GET', body, signal, headers = {} } = {}) {
  const csrf = document.cookie.split('; ').find(value => value.startsWith('ati_csrf='))?.split('=').slice(1).join('=') || '';
  const response = await fetch(`/api${path}`, {
    method, credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': decodeURIComponent(csrf), ...headers },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, data.detail);
  return data;
}

/** Dashboard endpoints for both legacy demos and authenticated wallet sessions. */
export const dashboardApi = {
  health: () => api('/health'),
  networkStatus: () => api('/network/status'),
  walletInfo: address => api(`/wallet/info${address ? `?address=${encodeURIComponent(address)}` : ''}`),
  policies: () => api('/guardrail/policies'),
  chat: body => api('/chat', { method: 'POST', body }),
  turn: (conversation, body) => api(`/history/conversations/${conversation}/turns`, { method: 'POST', body }),
  reviewApproval: body => api('/approval/action', { method: 'POST', body }),
  approvalStatus: (approvalId, sessionId) => api(`/approval/${encodeURIComponent(approvalId)}`, {
    headers: { 'X-Session-ID': sessionId },
  }),
  priceCurrent: () => api('/prices/current'),
  priceHistory: (tf = '24h') => api(`/prices/history?timeframe=${encodeURIComponent(tf)}`),
  priceComparison: () => api('/prices/comparison'),
  priceChainlink: () => api('/prices/chainlink'),
  priceAlerts: () => api('/prices/alerts'),
  addPriceAlert: (body) => api('/prices/alerts', { method: 'POST', body }),
  removePriceAlert: (id) => api(`/prices/alerts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

export function transactionForProvider(transaction) {
  const integers = new Set(['value', 'gas', 'gasPrice', 'maxFeePerGas', 'maxPriorityFeePerGas', 'nonce', 'chainId', 'type']);
  return Object.fromEntries(Object.entries(transaction).map(([key, value]) => [key,
    integers.has(key) ? `0x${BigInt(value).toString(16)}` : value]));
}

export function displayDecimal(value, places = 6) {
  const [whole, fraction = ''] = String(value).split('.');
  return fraction.length > places ? `${whole}.${fraction.slice(0, places)}…` : String(value);
}
