const { test, expect } = require('@playwright/test');

async function installWallet(page, { connected = true } = {}) {
  // Keep local E2E independent of external font/CDN availability.
  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, route => route.abort());
  await page.addInitScript(({ rpc, connected }) => {
    const listeners = new Map();
    const accounts = ['0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266', '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'];
    let index = Number(sessionStorage.getItem('test_wallet_index') || 0);
    let granted = connected;
    window.__testWallet = {
      sends: 0, connects: 0, signatures: 0,
      switchAccount(value) {
        index = value;
        sessionStorage.setItem('test_wallet_index', String(index));
        for (const listener of listeners.get('accountsChanged') || []) listener([accounts[index]]);
      },
    };
    window.ethereum = {
      on(event, listener) { const values = listeners.get(event) || new Set(); values.add(listener); listeners.set(event, values); },
      removeListener(event, listener) { listeners.get(event)?.delete(listener); },
      async request({ method, params = [] }) {
        if (method === 'eth_accounts') return granted ? [accounts[index]] : [];
        if (method === 'eth_requestAccounts') { granted = true; window.__testWallet.connects++; return [accounts[index]]; }
        if (method === 'eth_chainId') return '0x7a69';
        if (method === 'wallet_requestPermissions') return [{ parentCapability: 'eth_accounts' }];
        if (method === 'personal_sign') { window.__testWallet.signatures++; method = 'eth_sign'; params = [params[1], params[0]]; }
        if (method === 'eth_sendTransaction') window.__testWallet.sends++;
        const response = await fetch(rpc, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
        const data = await response.json();
        if (data.error) throw Object.assign(new Error(data.error.message), { code: data.error.code });
        return data.result;
      },
    };
  }, { rpc: process.env.WALLET_E2E_RPC, connected });
}

async function signIn(page) {
  // A single app action handles extension permission and authenticated login.
  if (!(await page.locator('#wallet-status').textContent()).includes('Agent ready')) {
    await page.locator('#wallet-connect').click();
  }
  await expect(page.locator('#wallet-status')).toContainText('Agent ready', { timeout: 20000 });
  await expect(page.locator('#conversation-list option').first()).toBeAttached();
  await expect(page.locator('#chat-input')).toBeEnabled();
}

test('legacy chat, timeline, approval and theme work with native browser modules', async ({ page }) => {
  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, route => route.abort());
  await page.route('**/api/health', route => route.fulfill({ json: {
    chain_id: 31337, wallet_history_enabled: false,
  } }));
  const parameters = { sender: '0x' + '11'.repeat(20), recipient: '0x' + '22'.repeat(20), amount: '1', chain_id: 31337 };
  await page.route('**/api/chat', route => route.fulfill({ json: {
    reply: 'Legacy proposal ready',
    timeline: [{ step_number: 1, name: 'Request received', status: 'SUCCESS', result: { operation: 'native_transfer' } }],
    requires_approval: true,
    guardrail_result: { pending_approval: { approval_id: 'legacy-approval', operation: 'native_transfer', parameters } },
  } }));
  let reviews = 0;
  await page.route('**/api/approval/action', route => {
    reviews++;
    const body = route.request().postDataJSON();
    expect(body.approval_id).toBe('legacy-approval');
    expect(body.action).toBe('APPROVE');
    expect(body.parameters).toEqual(parameters);
    expect(body.session_id).toBeTruthy();
    return route.fulfill({ json: { status: 'CONFIRMED', tx_hash: '0x123' } });
  });
  await page.goto('/');
  await expect(page.locator('#chat-history')).not.toBeEmpty();
  const theme = await page.locator('html').getAttribute('data-theme');
  await page.locator('#btn-toggle-theme').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme === 'dark' ? 'light' : 'dark');
  await page.locator('#chat-input').fill('Prepare a transfer');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#chat-history')).toContainText('Legacy proposal ready');
  await expect(page.locator('.step-num-badge')).toHaveText('1');
  await expect(page.locator('#approval-modal')).toHaveClass(/open/);
  await page.locator('#btn-modal-approve').click();
  await expect(page.locator('#approval-modal')).not.toHaveClass(/open/);
  await expect(page.locator('#chat-history')).toContainText('0x123');
  await page.locator('.step-details-toggle').click();
  await expect(page.locator('.step-details-box')).toHaveClass(/open/);
  expect(reviews).toBe(1);
});

test('A/B histories remain separate and reload restores the conversation', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  await page.locator('#chat-input').fill('Remember alpha');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#btn-send-message')).toBeEnabled();
  await expect(page.locator('#chat-history')).toContainText('Remember alpha');
  await page.reload();
  await expect(page.locator('#wallet-status')).toContainText('Agent ready');
  await expect(page.locator('#chat-history')).toContainText('Remember alpha');
  await page.evaluate(() => window.__testWallet.switchAccount(1));
  await expect(page.locator('#chat-history')).not.toContainText('Remember alpha');
  await signIn(page);
  await expect(page.locator('#chat-history')).not.toContainText('Remember alpha');
  await page.evaluate(() => window.__testWallet.switchAccount(0));
  await signIn(page);
  await expect(page.locator('#chat-history')).toContainText('Remember alpha');
  await page.screenshot({ path: '../.phase3/wallet-e2e/history.png', fullPage: true, animations: 'disabled' });
});

test('faucet is signed once in the wallet and becomes a matched on-chain transaction', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  // Use B, which has not claimed faucet in this fresh test context.
  await page.evaluate(() => window.__testWallet.switchAccount(1));
  await signIn(page);
  await page.locator('#chat-input').fill('Claim 10 AGNT from faucet');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#approval-modal')).toHaveClass(/open/);
  await expect(page.locator('#modal-sender')).toContainText('0x70997970');
  await page.locator('#btn-modal-approve').click();
  await expect(page.locator('#approval-modal')).not.toHaveClass(/open/);
  await expect(page.locator('#chat-history')).toContainText('Transaction submitted');
  expect(await page.evaluate(() => window.__testWallet.sends)).toBe(1);
  await expect(page.locator('#val-token-balance')).toHaveText(/^10(?:\.|$)/);
  await expect(async () => {
    await page.locator('#history-refresh').click();
    await expect(page.locator('#history-transactions')).toContainText('MATCHED');
  }).toPass({ timeout: 30000, intervals: [1000, 2000, 4000] });
});

test('a delayed A response cannot reopen or overwrite the B conversation', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  let release, fetched;
  const gate = new Promise(resolve => { release = resolve; });
  const received = new Promise(resolve => { fetched = resolve; });
  await page.route('**/api/history/conversations/*/turns', async route => {
    const response = await route.fetch();
    fetched();
    await gate;
    await route.fulfill({ response });
  });
  await page.locator('#chat-input').fill('delayed A message');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await received;
  await page.evaluate(() => window.__testWallet.switchAccount(1));
  await signIn(page);
  release();
  await expect(page.locator('#chat-history')).not.toContainText('delayed A message');
  await expect(page.locator('#header-wallet-address')).toContainText('0x7099');
  await expect(page.locator('#approval-modal')).not.toHaveClass(/open/);
});

test('logout from one tab clears private history in the other tab', async ({ page, context }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  const second = await context.newPage();
  await installWallet(second);
  await second.goto('/');
  await expect(second.locator('#wallet-status')).toContainText('Agent ready');
  await page.locator('#wallet-menu summary').click();
  await page.locator('#wallet-disconnect').click();
  await expect(second.locator('#wallet-status')).toContainText('Wallet disconnected');
  await expect(second.locator('#chat-history .chat-message')).toHaveCount(0);
  await expect(second.locator('#btn-send-message')).toBeDisabled();
});

test('wallet controls and history fit a mobile viewport and support Vietnamese', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  await page.locator('#btn-toggle-lang').click();
  await expect(page.locator('#wallet-status')).toContainText('Agent sẵn sàng');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../.phase3/wallet-e2e/mobile.png', fullPage: true, animations: 'disabled' });
});

test('the same Connect wallet action restores access when a login cookie expires', async ({ page, context }) => {
  await installWallet(page);
  await page.goto('/');
  await expect(page.locator('#wallet-connect')).toBeVisible();
  await expect(page.locator('#wallet-chat-gate')).toBeVisible();
  await expect(page.locator('#header-wallet-address')).toContainText('0xf39');
  await expect(page.locator('#chat-input')).toBeDisabled();
  await signIn(page);
  await context.clearCookies();
  await page.reload();
  await expect(page.locator('#wallet-connect')).toBeVisible();
  await expect(page.locator('#wallet-chat-guidance')).toContainText('Click Connect wallet');
  await signIn(page);
  await expect(page.locator('#wallet-chat-gate')).toBeHidden();
});

test('one app click connects a fresh wallet, verifies its signature and opens Agent', async ({ page }) => {
  await installWallet(page, { connected: false });
  await page.goto('/');
  await expect(page.locator('#wallet-connect')).toBeVisible();
  await expect(page.locator('#wallet-sign-in')).toHaveCount(0);
  await page.locator('#wallet-connect').click();
  await expect(page.locator('#wallet-status')).toContainText('Agent ready', { timeout: 20000 });
  await expect(page.locator('#chat-input')).toBeEnabled();
  await expect(page.locator('#wallet-connect')).toBeHidden();
  await expect(page.locator('#wallet-menu')).toBeVisible();
  expect(await page.evaluate(() => ({ connects: window.__testWallet.connects, signatures: window.__testWallet.signatures, sends: window.__testWallet.sends })))
    .toEqual({ connects: 1, signatures: 1, sends: 0 });
  await page.locator('#chat-input').fill('Check my ETH balance');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#btn-send-message')).toBeEnabled();
  await expect(page.locator('#chat-history')).toContainText('ETH');
});

test('opening a wallet sidebar keeps the composer usable without a tall header', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  for (const [width, height] of [[1365, 768], [1092, 700], [900, 720], [820, 720], [390, 640], [1536, 600]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(page.locator('#chat-input')).toBeInViewport({ ratio: 1 });
    await expect(page.locator('#btn-send-message')).toBeInViewport({ ratio: 1 });
    const header = await page.locator('.app-header').boundingBox();
    expect(header.height, `Header too tall at ${width}x${height}`).toBeLessThan(width > 700 ? 155 : 205);
    const messages = await page.locator('#chat-history').boundingBox();
    expect(messages.height).toBeGreaterThan(120);
    await expect.poll(async () => {
      const last = await page.locator('#chat-history .chat-message').last().boundingBox();
      const history = await page.locator('#chat-history').boundingBox();
      return last.y + last.height <= history.y + history.height + 1;
    }).toBe(true);
    await expect(page.locator('#wallet-connect')).toBeHidden();
    await page.screenshot({ path: `../.phase3/wallet-e2e/sidebar-${width}-${height}.png`, fullPage: true, animations: 'disabled' });
  }
});

test('header, composer and panels remain inside the viewport at phone, tablet and desktop sizes', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await signIn(page);
  await page.locator('#btn-toggle-lang').click();
  for (const width of [360, 390, 768, 1024, 1280, 1536]) {
    await page.setViewportSize({ width, height: 900 });
    const problems = await page.evaluate(() => {
      const selectors = ['.app-header', '#panel-chat', '#panel-blockchain', '#panel-activity', '#wallet-controls', '#chat-form', '#chat-input', '#btn-send-message'];
      return selectors.filter(selector => {
        const box = document.querySelector(selector).getBoundingClientRect();
        return box.x < -1 || box.right > window.innerWidth + 1 || box.width < 20 || box.height < 15;
      });
    });
    expect(problems, `Layout overflow at ${width}px`).toEqual([]);
    if (width >= 1440) {
      const bounds = await page.locator('#panel-chat').boundingBox();
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(901);
    }
    if (width < 820) {
      await page.locator('#panel-blockchain').scrollIntoViewIfNeeded();
      await expect(page.locator('#panel-blockchain .panel-title')).toBeInViewport();
      await page.screenshot({ path: `../.phase3/wallet-e2e/assets-${width}.png`, animations: 'disabled' });
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    await page.screenshot({ path: `../.phase3/wallet-e2e/layout-${width}.png`, fullPage: true, animations: 'disabled' });
  }
});
