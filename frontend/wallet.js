import { api, transactionForProvider } from './api.js';

export const sameAddress = (left, right) => Boolean(left && right && left.toLowerCase() === right.toLowerCase());

/** One controller owns account/context generations. Stale responses never update the view. */
export class WalletController extends EventTarget {
  constructor(chainId) {
    super();
    this.expectedChain = chainId;
    this.providers = new Map();
    this.generation = 0;
    this.status = 'disconnected';
    this.context = null;
    this.address = null;
    this.provider = null;
    this.conversation = null;
    this.signing = false;
    this.authenticating = false;
    this.connecting = false;
    this.authRevocation = Promise.resolve();
    this.channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('ati-wallet-auth');
    this.channel?.addEventListener('message', () => {
      this.invalidate('signedOut');
    });
  }

  discover(surface = window) {
    this.surface = surface;
    this.announced = event => {
      const detail = event.detail;
      if (!detail?.provider?.request || !detail.info?.uuid) return;
      if (this.providers.get('injected')?.provider === detail.provider) this.providers.delete('injected');
      this.providers.set(detail.info.uuid, { name: String(detail.info.name).slice(0, 80), provider: detail.provider });
      this.dispatchEvent(new Event('providers'));
    };
    surface.addEventListener('eip6963:announceProvider', this.announced);
    surface.dispatchEvent(new Event('eip6963:requestProvider'));
    if (surface.ethereum?.request && ![...this.providers.values()].some(item => item.provider === surface.ethereum)) {
      this.providers.set('injected', { name: surface.ethereum.isMetaMask ? 'MetaMask' : 'Browser wallet', provider: surface.ethereum });
    }
  }

  get ready() { return this.status === 'ready' && Boolean(this.context); }
  current(generation) { return this.generation === generation; }
  changed() { this.dispatchEvent(new Event('change')); }

  invalidate(status = 'switching') {
    const previous = this.context;
    this.generation++;
    this.context = null;
    this.conversation = null;
    this.status = status;
    this.changed();
    // Server handles in-flight signing conservatively; a popup cannot be cancelled here.
    this.authRevocation = this.authRevocation.catch(() => {}).then(async () => {
      if (previous) await api(`/wallet-contexts/${previous.id}/revoke`, { method: 'POST' });
    });
    return this.generation;
  }

  attach(provider) {
    if (this.provider && this.accountListener) {
      this.provider.removeListener?.('accountsChanged', this.accountListener);
      this.provider.removeListener?.('chainChanged', this.chainListener);
      this.provider.removeListener?.('disconnect', this.disconnectListener);
    }
    this.provider = provider;
    this.accountListener = accounts => this.select(accounts[0] || null, this.chainId);
    this.chainListener = chain => this.select(this.address, Number(BigInt(chain)));
    this.disconnectListener = () => this.invalidate('offline');
    provider.on?.('accountsChanged', this.accountListener);
    provider.on?.('chainChanged', this.chainListener);
    provider.on?.('disconnect', this.disconnectListener);
  }

  select(address, chainId) {
    if (sameAddress(this.address, address) && this.chainId === chainId && this.status !== 'offline') return;
    this.invalidate();
    this.address = address;
    this.chainId = chainId;
    this.status = !address ? 'disconnected' : chainId !== this.expectedChain ? 'wrongNetwork' : 'signIn';
    this.changed();
  }

  async connect(providerId, requestSelection = false) {
    if (this.authenticating || this.signing) throw new Error('Finish the open wallet request first.');
    const selected = this.providers.get(providerId);
    if (!selected) throw new Error('No browser wallet found.');
    if (this.provider !== selected.provider) {
      this.invalidate();
      this.attach(selected.provider);
    }
    if (requestSelection) {
      try { await this.provider.request({ method: 'wallet_requestPermissions', params: [{ eth_accounts: {} }] }); }
      catch (error) { if (error.code !== -32601 && error.code !== 4200) throw error; }
    }
    const accounts = await this.provider.request({ method: 'eth_requestAccounts' });
    const chainId = Number(BigInt(await this.provider.request({ method: 'eth_chainId' })));
    this.select(accounts[0] || null, chainId);
  }

  async switchNetwork() {
    if (!this.provider) throw new Error('Connect a wallet first.');
    await this.provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: `0x${this.expectedChain.toString(16)}` }] });
  }

  async assertAccount(generation) {
    const [accounts, chain] = await Promise.all([
      this.provider.request({ method: 'eth_accounts' }), this.provider.request({ method: 'eth_chainId' }),
    ]);
    if (!this.current(generation) || !sameAddress(accounts[0], this.address) || Number(BigInt(chain)) !== this.expectedChain) {
      throw new Error('Wallet account or network changed. Reconnect before continuing.');
    }
  }

  async authenticate() {
    if (this.authenticating || this.signing || !this.address || this.chainId !== this.expectedChain) return;
    const generation = this.generation;
    this.authenticating = true;
    this.status = 'authenticating';
    this.changed();
    try {
      // Verification atomically revokes the previous browser session even if an
      // earlier context-revoke request was lost while offline.
      await this.authRevocation.catch(() => {});
      await this.assertAccount(generation);
      const challenge = await api('/auth/challenge', { method: 'POST', body: { address: this.address, chain_id: this.chainId } });
      if (!this.current(generation)) return;
      const bytes = new TextEncoder().encode(challenge.message);
      const hex = `0x${Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')}`;
      const signature = await this.provider.request({ method: 'personal_sign', params: [hex, this.address] });
      await this.assertAccount(generation);
      await api('/auth/verify', { method: 'POST', body: { challenge_id: challenge.challenge_id, signature } });
      this.channel?.postMessage('identity-changed');
      if (!this.current(generation)) return;
      const context = await api('/wallet-contexts', { method: 'POST', body: { chain_id: this.chainId } });
      if (!this.current(generation)) return;
      this.context = context;
      this.status = 'ready';
    } finally {
      this.authenticating = false;
      if (this.current(generation)) {
        if (!this.context) this.status = 'signIn';
        this.changed();
      }
    }
  }

  async restore() {
    const provider = this.providers.get('injected') || this.providers.values().next().value;
    if (!provider) return;
    this.attach(provider.provider);
    const generation = this.generation;
    try {
      const [accounts, chain] = await Promise.all([
        this.provider.request({ method: 'eth_accounts' }), this.provider.request({ method: 'eth_chainId' }),
      ]);
      if (!this.current(generation)) return;
      this.select(accounts[0] || null, Number(BigInt(chain)));
      if (!this.address || this.chainId !== this.expectedChain) return;
      const selectedGeneration = this.generation;
      // Extension permission is independent of the server login cookie. A 401
      // must leave the detected account visible with a Sign in action.
      const me = await api('/auth/me');
      if (!this.current(selectedGeneration)) return;
      if (!sameAddress(me.address, this.address) || this.chainId !== this.expectedChain) return;
      const context = await api('/wallet-contexts', { method: 'POST', body: { chain_id: this.chainId } });
      if (!this.current(selectedGeneration)) return;
      this.context = context;
      this.status = 'ready';
      this.changed();
    } catch (error) { if (error.status !== 401) this.dispatchEvent(new CustomEvent('error', { detail: error })); }
  }

  async connectAndSignIn(providerId, requestSelection = false) {
    if (this.connecting) return;
    this.connecting = true;
    this.changed();
    try {
      await this.connect(providerId, requestSelection);
      if (this.address && this.chainId !== this.expectedChain) {
        await this.switchNetwork();
        const chainId = Number(BigInt(await this.provider.request({ method: 'eth_chainId' })));
        this.select(this.address, chainId);
      }
      if (!this.ready && this.address && this.chainId === this.expectedChain) await this.authenticate();
    } finally {
      this.connecting = false;
      this.changed();
    }
  }

  async disconnect() {
    this.invalidate('signedOut');
    this.address = null;
    await this.authRevocation.catch(() => {});
    try { await api('/auth/logout', { method: 'POST' }); }
    catch (error) { if (error.status !== 401) throw error; }
    this.channel?.postMessage('signed-out');
    this.changed();
  }

  async submit(approval, action) {
    if (!this.ready || this.signing || this.authenticating) throw new Error('Sign in with the correct wallet first.');
    const generation = this.generation;
    const body = { context_id: this.context.id, generation: this.context.generation, parameter_hash: approval.parameter_hash };
    if (action === 'REJECT') return api(`/wallet-proposals/${approval.approval_id}/reject`, { method: 'POST', body });
    this.signing = true;
    this.changed();
    let submission;
    try {
      await this.assertAccount(generation);
      submission = await api(`/wallet-proposals/${approval.approval_id}/authorize`, { method: 'POST', body });
      // Persist only the write-only report capability, not auth or signed payloads.
      const pending = { submission_id: submission.submission_id, report_token: submission.report_token };
      sessionStorage.setItem(`ati_submission_${submission.submission_id}`, JSON.stringify(pending));
      await this.assertAccount(generation);
      const hash = await this.provider.request({ method: 'eth_sendTransaction', params: [transactionForProvider(submission.transaction)] });
      pending.tx_hash = hash;
      sessionStorage.setItem(`ati_submission_${submission.submission_id}`, JSON.stringify(pending));
      await api(`/wallet-submissions/${submission.submission_id}/report`, { method: 'POST', body: { report_token: submission.report_token, tx_hash: hash } });
      sessionStorage.removeItem(`ati_submission_${submission.submission_id}`);
      return { status: 'SUBMITTED', tx_hash: hash };
    } catch (error) {
      if (submission) {
        await api(`/wallet-submissions/${submission.submission_id}/report`, { method: 'POST', body: {
          report_token: submission.report_token, rejected: error.code === 4001,
        } }).catch(() => {});
      }
      throw error;
    } finally { this.signing = false; this.changed(); }
  }

  async retryReports() {
    const keys = Object.keys(sessionStorage).filter(key => key.startsWith('ati_submission_')).slice(0, 50);
    for (const key of keys) {
      try {
        const { submission_id: id, ...body } = JSON.parse(sessionStorage.getItem(key));
        if (!body.tx_hash) continue; // A missing hash never authorizes sending again.
        await api(`/wallet-submissions/${id}/report`, { method: 'POST', body });
        sessionStorage.removeItem(key);
      } catch { /* Keep bounded recovery metadata until the next explicit refresh. */ }
    }
  }
}
