import { api } from './api.js';
import { t } from './i18n.js';

/** Owner history uses textContent; no server/provider content is inserted as HTML. */
export class HistoryView {
  constructor(wallet, { clear, append, timeline, approval, error }) {
    this.wallet = wallet;
    this.hooks = { clear, append, timeline, approval, error };
    this.conversations = [];
    this.readOnly = false;
    this.epoch = 0;
    const run = action => {
      const generation = wallet.generation;
      Promise.resolve().then(action).catch(problem => {
        if (wallet.current(generation)) error(problem);
      });
    };
    this.nodes = Object.fromEntries(['conversation-list', 'conversation-more', 'history-new', 'history-rename', 'history-archive',
      'history-transactions', 'transactions-more', 'history-audits', 'audits-more', 'history-refresh', 'history-older'].map(id => [id, document.getElementById(id)]));
    this.nodes['conversation-list'].addEventListener('change', () => run(() => this.open(this.nodes['conversation-list'].value)));
    this.nodes['history-new'].addEventListener('click', () => run(() => this.create()));
    this.nodes['history-rename'].addEventListener('click', () => run(() => this.rename()));
    this.nodes['history-archive'].addEventListener('click', () => run(() => this.archive()));
    this.nodes['history-refresh'].addEventListener('click', () => run(() => Promise.all([
      this.refreshTransactions(), this.refreshAudit(), this.loadMessages(),
    ])));
    this.nodes['transactions-more'].addEventListener('click', () => run(() => this.refreshTransactions(this.txCursor)));
    this.nodes['audits-more'].addEventListener('click', () => run(() => this.refreshAudit(this.auditCursor)));
    this.nodes['conversation-more'].addEventListener('click', () => run(() => this.list(this.conversationCursor)));
    this.nodes['history-older'].addEventListener('click', () => run(() => this.loadMessages(this.messageCursor, true)));
  }

  clear() {
    this.epoch++;
    this.wallet.conversation = null;
    this.conversations = [];
    this.readOnly = false;
    for (const name of ['conversation-list', 'history-transactions', 'history-audits']) this.nodes[name].replaceChildren();
    for (const name of ['history-older', 'transactions-more', 'audits-more', 'conversation-more']) this.nodes[name].hidden = true;
    this.hooks.clear();
  }

  async list(cursor) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const result = await api(`/history/conversations${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!this.wallet.current(generation) || !this.wallet.ready) return;
    this.conversations = cursor ? [...this.conversations, ...result.items] : result.items;
    this.conversationCursor = result.next_cursor;
    this.nodes['conversation-more'].hidden = !result.next_cursor;
    const select = this.nodes['conversation-list'];
    select.replaceChildren();
    for (const conversation of this.conversations) {
      const option = document.createElement('option');
      option.value = conversation.id;
      option.textContent = conversation.title + (conversation.deployment_id === this.wallet.context.deployment_id ? '' : ` (${t('wallet.previousNetwork')})`);
      select.append(option);
    }
    if (this.wallet.conversation) select.value = this.wallet.conversation;
  }

  async initialize() {
    const generation = this.wallet.generation;
    await this.list();
    if (!this.wallet.current(generation) || !this.wallet.ready) return;
    const current = this.conversations.find(item => item.deployment_id === this.wallet.context.deployment_id);
    if (current) await this.open(current.id);
    else await this.create();
    await Promise.all([this.refreshTransactions(), this.refreshAudit()]);
  }

  async create() {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const conversation = await api('/history/conversations', { method: 'POST', body: {
      context_id: this.wallet.context.id, generation: this.wallet.context.generation, title: t('wallet.newChat'),
    } });
    if (!this.wallet.current(generation)) return;
    await this.list();
    if (!this.wallet.current(generation)) return;
    await this.open(conversation.id);
  }

  async open(id) {
    if (!id || !this.wallet.ready) return;
    this.epoch++;
    this.wallet.conversation = id;
    this.nodes['conversation-list'].value = id;
    this.readOnly = this.conversations.find(item => item.id === id)?.deployment_id !== this.wallet.context.deployment_id;
    this.hooks.clear();
    this.displayTurns = [];
    await this.loadMessages();
  }

  async loadMessages(cursor, older = false) {
    const generation = this.wallet.generation;
    const epoch = this.epoch;
    const id = this.wallet.conversation;
    if (!id) return;
    const result = await api(`/history/conversations/${id}/messages${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!this.wallet.current(generation) || this.epoch !== epoch) return;
    this.displayTurns = older ? [...this.displayTurns, ...result.items] : result.items;
    this.messageCursor = result.next_cursor;
    this.nodes['history-older'].hidden = !result.next_cursor;
    this.hooks.clear();
    for (const turn of [...this.displayTurns].reverse()) {
      for (const message of turn.messages) this.hooks.append(message.role === 'user' ? 'user' : 'agent', message.content);
      if (!['COMPLETED', 'FAILED'].includes(turn.status)) this.hooks.append('agent', t('wallet.turnStatus', { status: turn.status }));
    }
    const recent = this.displayTurns[0];
    if (recent?.response?.timeline) this.hooks.timeline(recent.response.timeline);
    // Never reopen old approvals automatically on reload.
  }

  async rename() {
    if (!this.wallet.ready || !this.wallet.conversation) return;
    const title = window.prompt(t('wallet.renamePrompt'));
    if (!title?.trim()) return;
    await api(`/history/conversations/${this.wallet.conversation}`, { method: 'PATCH', body: { title: title.trim().slice(0, 120) } });
    await this.list();
  }

  async archive() {
    if (!this.wallet.ready || !this.wallet.conversation) return;
    const generation = this.wallet.generation;
    await api(`/history/conversations/${this.wallet.conversation}`, { method: 'PATCH', body: { archived: true } });
    if (!this.wallet.current(generation)) return;
    this.wallet.conversation = null;
    await this.initialize();
  }

  async refreshTransactions(cursor) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const result = await api(`/history/transactions${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!this.wallet.current(generation) || !this.wallet.ready) return;
    const container = this.nodes['history-transactions'];
    if (!cursor) container.replaceChildren();
    for (const transaction of result.items) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'history-entry';
      const outcome = transaction.receipt_status === 0 ? ` · ${t('wallet.reverted')}` : transaction.receipt_status === 1 ? ` · ${t('wallet.succeeded')}` : '';
      row.textContent = `${transaction.operation} · ${transaction.parameters.amount} ${transaction.parameters.token_symbol}\n${transaction.status}${outcome} · ${transaction.verification_status}\nChain ${transaction.parameters.chain_id} · ${new Date(transaction.created_at * 1000).toLocaleString()}`;
      row.addEventListener('click', () => this.showTransaction(transaction.proposal_id).catch(this.hooks.error));
      container.append(row);
    }
    if (!container.childElementCount) container.textContent = t('wallet.noTransactions');
    this.txCursor = result.next_cursor;
    this.nodes['transactions-more'].hidden = !result.next_cursor;
  }

  async showTransaction(proposalId) {
    const generation = this.wallet.generation;
    const result = await api(`/wallet-proposals/${proposalId}`);
    if (!this.wallet.current(generation)) return;
    for (const attempt of result.attempts) {
      const receipt = attempt.receipt;
      this.hooks.append('agent', `${attempt.status} · ${attempt.verification_status}\n${attempt.tx_hash || t('wallet.unknownHash')}${receipt ? `\nReceipt: ${receipt.receipt_status} · ${receipt.confirmations} confirmations` : ''}`);
      if (attempt.tx_hash && result.parameters.chain_id === 11155111) {
        this.hooks.append('agent', `[Etherscan](https://sepolia.etherscan.io/tx/${attempt.tx_hash})`);
      }
      if (!attempt.tx_hash && ['UNKNOWN', 'AWAITING_SIGNATURE'].includes(attempt.status)) {
        const txHash = window.prompt(t('wallet.recoverHash'));
        if (txHash?.trim()) {
          await api(`/wallet-submissions/${attempt.id}/recover`, { method: 'POST', body: { tx_hash: txHash.trim() } });
          await this.refreshTransactions();
        }
      }
    }
  }

  async refreshAudit(cursor) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const result = await api(`/history/audits${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!this.wallet.current(generation) || !this.wallet.ready) return;
    const container = this.nodes['history-audits'];
    if (!cursor) container.replaceChildren();
    for (const item of result.items) {
      const row = document.createElement('div');
      row.className = 'history-entry';
      row.textContent = `${item.event_type} · ${new Date(item.created_at * 1000).toLocaleString()}`;
      container.append(row);
    }
    this.auditCursor = result.next_cursor;
    this.nodes['audits-more'].hidden = !result.next_cursor;
  }
}
