const { test, expect } = require('@playwright/test');
const path = require('node:path');

// Serve source modules in-process so UI checks need no backend, chain, or dev server.
test.use({ baseURL: 'http://localhost:4179' });

test.beforeEach(async ({ page }) => {
  await page.route('http://localhost:4179/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    const root = path.resolve(__dirname, '../..');
    const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
    if (!file.startsWith(root + path.sep)) return route.abort();
    return route.fulfill({ path: file });
  });
  await page.route(/https:\/\/(fonts\.|cdn\.)/, route => route.abort());
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const responses = {
      '/api/health': { chain_id: 31337, wallet_history_enabled: false },
      '/api/network/status': { name: 'Local', chain_id: 31337 },
      '/api/wallet/info': { address: '0x' + '11'.repeat(20), native_balance: '1.25', token_balance: '250' },
      '/api/guardrail/config': { token_address: '0x' + '22'.repeat(20), token_limits: {}, recipient_whitelist: [], contract_transfer_limit: { per_tx_limit: '500', raw_limit: String(500n * 10n ** 18n), owner: '0x' + '11'.repeat(20), address: '0x' + '22'.repeat(20), decimals: 18, chain_id: 31337, setter_selector: '0x12345678' } },
      '/api/prices/history': { prices: [] },
      '/api/prices/alerts': [],
      '/api/prices/comparison': { rates: {} },
      '/api/history/conversations': { items: [{ id: 'first', title: 'First conversation', deployment_id: 'local' }, { id: 'second', title: '<img src=x onerror=alert(1)>', deployment_id: 'local' }] },
      '/api/history/conversations/second/messages': { items: [{ status: 'COMPLETED', messages: [{ role: 'user', content: 'Saved message' }] }] },
    };
    return route.fulfill({ json: responses[path] || {} });
  });
});

test('tool pages preserve chat drafts and forms, support browser back, and isolate settings', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#val-token-balance')).toHaveText('250');
  await expect(page.locator('.app-header #val-native-balance')).toHaveText('1.25');
  await expect(page.locator('#btn-toggle-theme')).toBeHidden();
  await page.locator('#chat-input').fill('Keep this draft');
  await page.locator('[data-page-link="guardrails"]').click();
  await expect(page.locator('#panel-chat')).toBeHidden();
  await page.locator('#input-per-tx-token').fill('37');
  await page.locator('[data-page-link="dry-run"]').click();
  await page.locator('#input-test-amount').fill('4');
  await page.goBack();
  await expect(page.locator('#input-per-tx-token')).toHaveValue('37');
  await page.locator('[data-page-link="prices"]').click();
  await expect(page.locator('#price-tracker-card')).toBeVisible();
  await page.locator('#page-prices a[href="#chat"]').click();
  await expect(page.locator('#chat-input')).toHaveValue('Keep this draft');
  await page.locator('#history-new').click();
  await expect(page.locator('#chat-input')).toHaveValue('');
  await page.locator('#btn-settings').click();
  await expect(page.locator('#settings-dialog')).toBeVisible();
  const theme = await page.locator('html').getAttribute('data-theme');
  await page.locator('#btn-toggle-theme').click();
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', theme);
  await page.locator('#btn-toggle-lang').click();
  await expect(page.locator('#settings-title')).toHaveText('Cài đặt');
  await page.keyboard.press('Escape');
  await expect(page.locator('#settings-dialog')).toBeHidden();
  await expect(page.locator('#btn-settings')).toBeFocused();
  await page.goto('/#dry-run');
  await expect(page.locator('#form-test-block')).toBeVisible();
  expect(errors).toEqual([]);
});

test('both sidebars collapse, restore, and persist without horizontal overflow', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#chat-history')).not.toBeEmpty();
  await page.setViewportSize({ width: 1440, height: 900 });
  const original = await page.locator('#panel-chat').boundingBox();
  for (const side of ['left', 'right']) await page.locator(`[data-hide-panel="${side}"]`).click();
  await expect(page.locator('#panel-blockchain')).toBeHidden();
  await expect(page.locator('#panel-activity')).toBeHidden();
  expect((await page.locator('#panel-chat').boundingBox()).width).toBeGreaterThan(original.width + 400);
  await page.reload();
  await expect(page.locator('#panel-blockchain')).toBeHidden();
  for (const side of ['left', 'right']) await page.locator(`#show-${side}-panel`).click();
  for (const width of [360, 390, 768, 1024, 1280, 1536]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('#btn-send-message')).toBeInViewport({ ratio: 1 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('[data-page-link="guardrails"]').click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('#btn-settings').click();
    await expect(page.locator('#btn-toggle-lang')).toBeInViewport();
    await page.keyboard.press('Escape');
    await page.locator('[data-page-link="chat"]').click();
    await expect(page.locator('#panel-chat')).toBeVisible();
    if (width === 390 || width === 1536) {
      await page.screenshot({ path: `../.phase3/workspace-${width}.png`, fullPage: true, animations: 'disabled' });
    }
  }
});

test('wallet actions live next to settings and blockchain cards stay outside the dialog', async ({ page }) => {
  await page.clock.install();
  const address = '0x' + '11'.repeat(20);
  const responses = {
    '/api/health': { chain_id: 31337, wallet_history_enabled: true },
    '/api/auth/me': { address },
    '/api/wallet-contexts': { id: 'context', generation: 1, deployment_id: 'local' },
    '/api/history/conversations/first/messages': { items: [] },
    '/api/history/transactions': { items: [] },
    '/api/history/audits': { items: [] },
  };
  for (const [url, json] of Object.entries(responses)) {
    await page.route(`**${url}`, route => route.fulfill({ json }));
  }
  await page.addInitScript(address => {
    window.ethereum = {
      on() {}, removeListener() {},
      async request({ method }) {
        if (method === 'eth_accounts') return [address];
        if (method === 'eth_chainId') return '0x7a69';
        if (method === 'eth_sendTransaction') return new Promise(resolve => { window.finishWalletSend = resolve; });
        return [];
      },
    };
  }, address);
  await page.goto('/');
  await expect(page.locator('#wallet-status')).toContainText('Agent ready');
  await page.route('**/api/history/conversations/first/turns', route => route.fulfill({ json: {
    status: 'COMPLETED', response: { reply: 'Balance checked', timeline: [] },
  } }));
  await page.route('**/api/history/conversations', route => route.fulfill({ json: {
    items: [{ id: 'first', title: 'Kiểm tra số dư ETH', deployment_id: 'local' }],
  } }));
  await page.locator('#chat-input').fill('Kiểm tra số dư ETH');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('[data-conversation-id="first"]')).toHaveText('Kiểm tra số dư ETH');
  await expect(page.locator('#chat-history')).toContainText('Balance checked');
  let transaction = {
    id: 'receipt-attempt', proposal_id: 'proposal', conversation_id: 'first',
    tx_hash: '0x' + 'ab'.repeat(32), created_at: Date.now() / 1000,
    status: 'SUBMITTED', verification_status: 'UNVERIFIED', receipt_status: null,
    operation: 'erc20_transfer', parameters: { amount: '10', token_symbol: 'AGNT', recipient: address, chain_id: 31337 },
  };
  await page.route('**/api/history/transactions', route => route.fulfill({ json: { items: [transaction] } }));
  await page.clock.fastForward(5000);
  await expect(page.locator('#chat-history')).not.toContainText('Transaction confirmed successfully');
  transaction = { ...transaction, status: 'MINED_SUCCESS', verification_status: 'MATCHED', receipt_status: 1 };
  await page.clock.fastForward(5000);
  await expect(page.locator('#chat-history')).toContainText('Transaction confirmed successfully on chain.');
  await expect(page.locator('#chat-history')).toContainText('10 AGNT');
  await page.clock.fastForward(5000);
  await expect(page.locator('#chat-history .message-bubble').filter({ hasText: 'Transaction confirmed successfully' })).toHaveCount(1);
  await expect(page.locator('.header-wallet-summary #wallet-menu')).toBeVisible();
  await expect(page.locator('#panel-activity #val-contract-address')).toBeVisible();
  await expect(page.locator('#panel-activity #val-gas-price')).toBeVisible();
  await page.locator('#wallet-menu summary').click();
  await expect(page.locator('#wallet-switch')).toBeVisible();
  await page.locator('#wallet-menu summary').click();
  await page.locator('#btn-settings').click();
  await expect(page.locator('.settings-group')).toHaveCount(2);
  await expect(page.locator('#settings-dialog #wallet-controls')).toHaveCount(0);
  await expect(page.locator('#settings-dialog .network-detail-card')).toHaveCount(0);
  await page.screenshot({ path: '../.phase3/settings-compact.png', animations: 'disabled' });
  await page.keyboard.press('Escape');
  for (const width of [360, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('#wallet-menu')).toBeInViewport();
    await expect(page.locator('#btn-settings')).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('#wallet-menu summary').click();
    await expect(page.locator('#wallet-switch')).toBeInViewport();
    await page.locator('#wallet-menu summary').click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/history/conversations/first/turns', route => route.fulfill({ json: {
    status: 'COMPLETED', response: { reply: 'Ready for approval', timeline: [], requires_approval: true, guardrail_result: {
      pending_approval: { approval_id: 'pending-signature', parameter_hash: 'hash', operation: 'erc20_transfer', parameters: { sender: address, recipient: address, amount: '5', token_symbol: 'AGNT', chain_id: 31337 } },
    } },
  } }));
  await page.route('**/api/wallet-proposals/pending-signature/authorize', route => route.fulfill({ json: {
    submission_id: 'waiting-signature', report_token: 'report', transaction: { from: address, to: address, value: '0', chainId: '31337' },
  } }));
  await page.route('**/api/wallet-submissions/waiting-signature/report', route => route.fulfill({ json: { status: 'RECORDED' } }));
  await page.locator('#chat-input').fill('Transfer 5 AGNT');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#approval-modal')).toHaveClass(/open/);
  await page.locator('#btn-modal-approve').click();
  await expect(page.locator('#approval-wallet-hint')).toBeVisible();
  await expect.poll(() => page.evaluate(() => typeof window.finishWalletSend)).toBe('function');
  await page.locator('#btn-close-approval').click();
  await expect(page.locator('#approval-modal')).not.toHaveClass(/open/);
  await page.evaluate(() => window.finishWalletSend('0x' + 'cd'.repeat(32)));
  await expect(page.locator('#chat-history')).toContainText('Transaction submitted');
  await expect(page.locator('#approval-modal')).not.toHaveClass(/open/);
});

test('conversation rows open saved messages, mark selection, and render titles as text', async ({ page }) => {
  let conversations = [{ id: 'first', title: 'First conversation', deployment_id: 'local' }, { id: 'second', title: '<img src=x onerror=alert(1)>', deployment_id: 'local' }];
  const changes = [];
  await page.route(/\/api\/history\/conversations(\?.*)?$/, route => {
    const archived = new URL(route.request().url()).searchParams.get('archived') === 'true';
    return route.fulfill({ json: { items: conversations.filter(item => Boolean(item.archived_at) === archived) } });
  });
  await page.route('**/api/history/conversations/first/messages', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/history/conversations/*', route => {
    const id = new URL(route.request().url()).pathname.split('/').pop();
    const body = route.request().method() === 'DELETE' ? { deleted: true } : route.request().postDataJSON();
    changes.push({ id, ...body });
    conversations = body.deleted ? conversations.filter(item => item.id !== id) : conversations.map(item => item.id === id ? { ...item, ...body, archived_at: body.archived === true ? 1 : body.archived === false ? null : item.archived_at } : item);
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await expect(page.locator('#chat-history')).not.toBeEmpty();
  await page.evaluate(async () => {
    const { HistoryView } = await import('/history.js');
    const wallet = { ready: true, generation: 1, current: () => true, context: { deployment_id: 'local' }, conversation: 'first' };
    const history = new HistoryView(wallet, {
      clear: () => document.getElementById('chat-history').replaceChildren(),
      append: (_, text) => { document.getElementById('chat-history').textContent += text; },
      timeline() {}, error(error) { throw error; },
    });
    document.getElementById('wallet-history').hidden = false;
    document.getElementById('history-archived-toggle').disabled = false;
    document.getElementById('history-empty').hidden = true;
    await history.list();
  });
  await expect(page.locator('.conversation-item')).toHaveCount(2);
  await expect(page.locator('#conversation-list img')).toHaveCount(0);
  await page.locator('[data-page-link="prices"]').click();
  await page.locator('[data-conversation-id="second"]').click();
  await expect(page.locator('#chat-history')).toHaveText('Saved message');
  await expect(page.locator('[data-conversation-id="second"]')).toHaveAttribute('aria-current', 'true');
  await expect(page).toHaveURL(/#chat$/);
  await page.locator('#history-search-toggle').click();
  await page.locator('#history-search').fill('First');
  await expect(page.locator('.conversation-row:visible')).toHaveCount(1);
  await page.locator('#history-search').fill('no results');
  await expect(page.locator('#history-no-results')).toBeVisible();
  await page.locator('#history-search').fill('');
  await page.locator('#history-recent-toggle').click();
  await expect(page.locator('#conversation-list')).toBeHidden();
  await page.locator('#history-recent-toggle').click();
  await page.locator('.conversation-row').first().hover();
  await page.locator('.conversation-row').first().locator('summary').click();
  page.once('dialog', dialog => dialog.accept('Renamed conversation'));
  await page.locator('[data-history-action="rename"][data-id="first"]').click();
  await expect(page.locator('[data-conversation-id="first"]')).toHaveText('Renamed conversation');
  await expect(page.locator('[data-conversation-id="second"]')).toHaveAttribute('aria-current', 'true');
  await page.locator('.conversation-row').first().hover();
  await page.locator('.conversation-row').first().locator('summary').click();
  await page.locator('[data-history-action="archive"][data-id="first"]').click();
  await expect(page.locator('.conversation-row')).toHaveCount(1);
  expect(changes).toEqual([{ id: 'first', title: 'Renamed conversation' }, { id: 'first', archived: true }]);
  await expect(page.locator('#chat-history')).toHaveText('Saved message');
  await page.locator('#history-archived-toggle').click();
  await expect(page.locator('[data-conversation-id="first"]')).toBeVisible();
  await page.locator('.conversation-row').first().hover();
  await page.locator('.conversation-row').first().locator('summary').click();
  await page.locator('[data-history-action="restore"]').click();
  await expect(page.locator('.conversation-row')).toHaveCount(2);
  await page.locator('.conversation-row').first().hover();
  await page.locator('.conversation-row').first().locator('summary').click();
  page.once('dialog', dialog => dialog.accept());
  await page.locator('[data-history-action="delete"][data-id="first"]').click();
  await expect(page.locator('[data-conversation-id="first"]')).toHaveCount(0);
  await expect(page.locator('#chat-history')).toHaveText('Saved message');
  expect(changes.slice(-2)).toEqual([{ id: 'first', archived: false }, { id: 'first', deleted: true }]);
  await page.locator('#btn-settings').click();
  await expect(page.locator('#settings-dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.screenshot({ path: '../.phase3/sidebar-chatgpt.png', animations: 'disabled' });
});

test('1H renders its data and an empty response shows a message instead of a blank chart', async ({ page }) => {
  await page.addInitScript(() => {
    window.Chart = class {
      constructor(canvas, configuration) { window.lastChart = configuration; }
      destroy() {}
    };
  });
  await page.route('**/api/prices/history?timeframe=1h', route => route.fulfill({ json: {
    timeframe: '1h', prices: [{ timestamp: 1730000000, price: 2284.94 }],
  } }));
  await page.goto('/#prices');
  await page.locator('[data-tf="1h"]').click();
  await expect(page.locator('#price-chart-canvas')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.lastChart?.data.datasets[0].data)).toEqual([2284.94]);
  expect(await page.evaluate(() => window.lastChart.data.datasets[0].pointRadius)).toBe(3);
  await page.locator('[data-tf="24h"]').click();
  await expect(page.locator('#price-chart-status')).toContainText('Price history is unavailable');
  await expect(page.locator('#price-chart-canvas')).toBeHidden();
});

test('contract owners can update the ceiling through MetaMask and application limits follow the confirmed value', async ({ page }) => {
  const address = '0x' + '11'.repeat(20);
  const contractAddress = '0x' + '22'.repeat(20);
  let ceiling = '500';
  let owner = address;
  await page.exposeFunction('confirmContractLimit', () => { ceiling = '1000'; });
  const responses = {
    '/api/health': { chain_id: 31337, wallet_history_enabled: true },
    '/api/auth/me': { address },
    '/api/wallet-contexts': { id: 'context', generation: 1, deployment_id: 'local' },
    '/api/history/conversations/first/messages': { items: [] },
    '/api/history/transactions': { items: [] }, '/api/history/audits': { items: [] },
  };
  for (const [url, json] of Object.entries(responses)) await page.route(`**${url}`, route => route.fulfill({ json }));
  await page.route('**/api/guardrail/config*', route => route.fulfill({ json: {
    token_address: contractAddress, per_tx_token_limit: 100, daily_token_limit: 1000, recipient_whitelist: [],
    contract_transfer_limit: { address: contractAddress, owner, per_tx_limit: ceiling, decimals: 18, chain_id: 31337, setter_selector: '0x12345678' },
  } }));
  await page.addInitScript(address => {
    window.adminTransactions = [];
    window.ethereum = {
      on() {}, removeListener() {},
      async request({ method, params }) {
        if (method === 'eth_accounts') return [address];
        if (method === 'eth_chainId') return '0x7a69';
        if (method === 'eth_call') return '0x';
        if (method === 'eth_estimateGas') return '0x10000';
        if (method === 'eth_sendTransaction') { window.adminTransactions.push(params[0]); return '0x' + 'cd'.repeat(32); }
        if (method === 'eth_getTransactionReceipt') { await window.confirmContractLimit(); return { status: '0x1' }; }
        return [];
      },
    };
  }, address);
  await page.goto('/#guardrails');
  await expect(page.locator('#wallet-status')).toContainText('Agent ready');
  await expect(page.locator('#input-per-tx-token')).toHaveAttribute('max', '500');
  await page.locator('#input-per-tx-token').fill('501');
  expect(await page.locator('#input-per-tx-token').evaluate(input => input.checkValidity())).toBe(false);
  await expect(page.locator('#input-daily-token')).not.toHaveAttribute('max');
  await expect(page.locator('#contract-limit-form')).toBeVisible();
  await page.locator('#input-contract-limit').fill('1000');
  await page.locator('#btn-save-contract-limit').click();
  await expect(page.locator('#contract-limit-status')).toContainText('Smart contract ceiling updated');
  await expect(page.locator('#input-per-tx-token')).toHaveAttribute('max', '1000');
  const sent = await page.evaluate(() => window.adminTransactions);
  expect(sent).toHaveLength(1);
  expect(sent[0].to).toBe(contractAddress);
  expect(BigInt('0x' + sent[0].data.slice(10))).toBe(1000n * 10n ** 18n);
  await expect(page.locator('#page-guardrails .panel-header #show-right-panel')).toBeVisible();
  await page.locator('#show-right-panel').click();
  await expect(page.locator('#panel-activity')).toBeHidden();
  await page.locator('#show-right-panel').click();
  await expect(page.locator('#panel-activity')).toBeVisible();
  await page.screenshot({ path: '../.phase3/contract-ceiling-owner.png', animations: 'disabled' });
  owner = '0x' + '33'.repeat(20);
  await page.reload();
  await expect(page.locator('#input-per-tx-token')).toHaveAttribute('max', '1000');
  await expect(page.locator('#contract-limit-form')).toBeHidden();
});

