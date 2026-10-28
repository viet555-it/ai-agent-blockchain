const { test, expect } = require('@playwright/test');

async function installWallet(page) {
  await page.addInitScript(({ rpc }) => {
    const listeners = new Map();
    const accounts = ['0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266', '0x70997970C51812dc3A010C7d01b50e0d17dc79C8'];
    let index = Number(sessionStorage.getItem('test_wallet_index') || 0);
    window.__testWallet = {
      sends: 0,
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
        if (['eth_accounts', 'eth_requestAccounts'].includes(method)) return [accounts[index]];
        if (method === 'eth_chainId') return '0x7a69';
        if (method === 'wallet_requestPermissions') return [{ parentCapability: 'eth_accounts' }];
        if (method === 'personal_sign') { method = 'eth_sign'; params = [params[1], params[0]]; }
        if (method === 'eth_sendTransaction') window.__testWallet.sends++;
        const response = await fetch(rpc, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
        const data = await response.json();
        if (data.error) throw Object.assign(new Error(data.error.message), { code: data.error.code });
        return data.result;
      },
    };
  }, { rpc: process.env.WALLET_E2E_RPC });
}

async function signIn(page) {
  await page.locator('#wallet-sign-in').click();
  await expect(page.locator('#wallet-status')).toContainText('History is saved');
  await expect(page.locator('#conversation-list option')).toHaveCount(1);
}

test('A/B histories remain separate and reload restores the conversation', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await page.locator('#wallet-connect').click();
  await signIn(page);
  await page.locator('#chat-input').fill('Remember alpha');
  await page.locator('#chat-form').evaluate(form => form.requestSubmit());
  await expect(page.locator('#btn-send-message')).toBeEnabled();
  await expect(page.locator('#chat-history')).toContainText('Remember alpha');
  await page.reload();
  await expect(page.locator('#wallet-status')).toContainText('History is saved');
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
  await page.locator('#wallet-connect').click();
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
  await expect(async () => {
    await page.locator('#history-refresh').click();
    await expect(page.locator('#history-transactions')).toContainText('MATCHED');
  }).toPass({ timeout: 30000, intervals: [1000, 2000, 4000] });
});

test('a delayed A response cannot reopen or overwrite the B conversation', async ({ page }) => {
  await installWallet(page);
  await page.goto('/');
  await page.locator('#wallet-connect').click();
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
  await page.locator('#wallet-connect').click();
  await signIn(page);
  const second = await context.newPage();
  await installWallet(second);
  await second.goto('/');
  await expect(second.locator('#wallet-status')).toContainText('History is saved');
  await page.locator('#wallet-disconnect').click();
  await expect(second.locator('#wallet-status')).toContainText('Signed out');
  await expect(second.locator('#chat-history .chat-message')).toHaveCount(0);
  await expect(second.locator('#btn-send-message')).toBeDisabled();
});

test('wallet controls and history fit a mobile viewport and support Vietnamese', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installWallet(page);
  await page.goto('/');
  await page.locator('#wallet-connect').click();
  await signIn(page);
  await page.locator('#btn-toggle-lang').click();
  await expect(page.locator('#wallet-status')).toContainText('Đã đăng nhập');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../.phase3/wallet-e2e/mobile.png', fullPage: true, animations: 'disabled' });
});
