import { api } from './api.js';
import { t, onLanguageChange } from './i18n.js';

/** Owner history uses textContent; no server/provider content is inserted as HTML. */
export class HistoryView {
  constructor(wallet, { clear, append, timeline, approval, error }) {
    this.wallet = wallet;
    this.hooks = { clear, append, timeline, approval, error };
    this.conversations = [];
    this.showArchived = false;
    this.readOnly = false;
    this.epoch = 0;
    this.transactionOutcomes = new Map();
    this.displayedOutcomes = new Set();
    const run = action => {
      const generation = wallet.generation;
      Promise.resolve().then(action).catch(problem => {
        if (wallet.current(generation)) error(problem);
      });
    };
    this.nodes = Object.fromEntries(['conversation-list', 'conversation-more', 'history-new',
      'history-transactions', 'transactions-more', 'history-audits', 'audits-more', 'history-refresh', 'history-older'].map(id => [id, document.getElementById(id)]));
    this.nodes['conversation-list'].addEventListener('click', event => {
      const action = event.target.closest('[data-history-action]');
      if (action && !action.disabled) {
        action.closest('details').open = false;
        const id = action.dataset.id;
        const handlers = { rename: () => this.rename(id), archive: () => this.archive(id), restore: () => this.restore(id), delete: () => this.delete(id) };
        run(handlers[action.dataset.historyAction]);
        return;
      }
      const button = event.target.closest('[data-conversation-id]');
      if (button && !button.disabled) run(async () => {
        await this.open(button.dataset.conversationId);
        window.location.hash = 'chat';
      });
    });
    this.nodes['history-new'].addEventListener('click', () => run(async () => {
      await this.create();
      window.location.hash = 'chat';
    }));
    document.getElementById('history-search').addEventListener('input', () => this.filterConversations());
    document.getElementById('history-archived-toggle').addEventListener('click', () => run(() => this.setArchivedView(!this.showArchived)));
    onLanguageChange(() => this.renderConversations());
    this.nodes['history-refresh'].addEventListener('click', () => run(() => Promise.all([
      this.list(), this.refreshTransactions(), this.refreshAudit(), this.loadMessages(),
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
    this.showArchived = false;
    this.readOnly = false;
    this.transactionOutcomes.clear();
    this.displayedOutcomes.clear();
    for (const name of ['conversation-list', 'history-transactions', 'history-audits']) this.nodes[name].replaceChildren();
    for (const name of ['history-older', 'transactions-more', 'audits-more', 'conversation-more']) this.nodes[name].hidden = true;
    document.getElementById('history-search').value = '';
    document.getElementById('history-no-results').hidden = true;
    this.hooks.clear();
  }

  async list(cursor) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const archived = this.showArchived;
    const params = new URLSearchParams();
    if (cursor) params.set('cursor', cursor);
    if (archived) params.set('archived', 'true');
    const result = await api(`/history/conversations${params.size ? `?${params}` : ''}`);
    if (!this.wallet.current(generation) || !this.wallet.ready || archived !== this.showArchived) return;
    this.conversations = cursor ? [...this.conversations, ...result.items] : result.items;
    this.conversationCursor = result.next_cursor;
    this.nodes['conversation-more'].hidden = !result.next_cursor;
    this.renderConversations();
  }

  renderConversations() {
    document.getElementById('history-list-heading').textContent = t(this.showArchived ? 'sidebar.archived' : 'sidebar.recent');
    document.getElementById('history-archived-toggle').setAttribute('aria-pressed', String(this.showArchived));
    const list = this.nodes['conversation-list'];
    list.replaceChildren();
    for (const conversation of this.conversations) {
      const row = document.createElement('div');
      row.className = 'conversation-row';
      row.dataset.active = String(conversation.id === this.wallet.conversation);
      row.dataset.title = conversation.title.toLocaleLowerCase();
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'conversation-item';
      option.dataset.conversationId = conversation.id;
      option.setAttribute('aria-current', String(conversation.id === this.wallet.conversation));
      option.textContent = conversation.title + (conversation.deployment_id === this.wallet.context.deployment_id ? '' : ` (${t('wallet.previousNetwork')})`);
      option.title = option.textContent;
      const menu = document.createElement('details');
      menu.className = 'conversation-menu';
      const summary = document.createElement('summary');
      summary.textContent = '···';
      summary.setAttribute('aria-label', t('sidebar.actions', { title: conversation.title }));
      const actions = document.createElement('div');
      actions.className = 'conversation-menu-items';
      for (const name of ['rename', this.showArchived ? 'restore' : 'archive', 'delete']) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.historyAction = name;
        button.dataset.id = conversation.id;
        button.textContent = t(`wallet.${name}`);
        actions.append(button);
      }
      menu.append(summary, actions);
      menu.addEventListener('toggle', () => {
        if (menu.open) list.querySelectorAll('details[open]').forEach(other => { if (other !== menu) other.open = false; });
      });
      row.append(option, menu);
      list.append(row);
    }
    this.filterConversations();
  }

  filterConversations() {
    const query = document.getElementById('history-search').value.trim().toLocaleLowerCase();
    let visible = 0;
    this.nodes['conversation-list'].querySelectorAll('.conversation-row').forEach(row => {
      row.hidden = !row.dataset.title.includes(query);
      if (!row.hidden) visible++;
    });
    document.getElementById('history-no-results').hidden = !query || visible > 0;
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
    this.showArchived = false;
    await this.list();
    if (!this.wallet.current(generation)) return;
    await this.open(conversation.id);
  }

  async open(id) {
    if (!id || !this.wallet.ready) return;
    this.epoch++;
    this.wallet.conversation = id;
    this.renderConversations();
    const conversation = this.conversations.find(item => item.id === id);
    this.archivedReadOnly = Boolean(conversation?.archived_at);
    this.readOnly = this.archivedReadOnly || conversation?.deployment_id !== this.wallet.context.deployment_id;
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
    this.displayedOutcomes.clear();
    for (const turn of [...this.displayTurns].reverse()) {
      for (const message of turn.messages) this.hooks.append(message.role === 'user' ? 'user' : 'agent', message.content);
      if (!['COMPLETED', 'FAILED'].includes(turn.status)) this.hooks.append('agent', t('wallet.turnStatus', { status: turn.status }));
      this.renderTurnOutcome(turn);
    }
    const recent = this.displayTurns[0];
    if (recent?.response?.timeline) this.hooks.timeline(recent.response.timeline);
    this.renderTransactionOutcomes();
    // Never reopen old approvals automatically on reload.
  }

  async rename(id = this.wallet.conversation) {
    if (!this.wallet.ready || !id) return;
    const generation = this.wallet.generation;
    const title = window.prompt(t('wallet.renamePrompt'));
    if (!title?.trim()) return;
    if (!this.wallet.current(generation)) return;
    await api(`/history/conversations/${id}`, { method: 'PATCH', body: { title: title.trim().slice(0, 120) } });
    if (!this.wallet.current(generation)) return;
    await this.list();
  }

  async archive(id = this.wallet.conversation) {
    if (!this.wallet.ready || !id) return;
    const generation = this.wallet.generation;
    await api(`/history/conversations/${id}`, { method: 'PATCH', body: { archived: true } });
    if (!this.wallet.current(generation)) return;
    if (id !== this.wallet.conversation) { await this.list(); return; }
    this.wallet.conversation = null;
    await this.initialize();
  }

  async setArchivedView(archived) {
    if (!this.wallet.ready) return;
    this.showArchived = archived;
    this.conversationCursor = null;
    await this.list();
  }

  async restore(id) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    await api(`/history/conversations/${id}`, { method: 'PATCH', body: { archived: false } });
    if (!this.wallet.current(generation)) return;
    this.showArchived = false;
    await this.list();
    if (this.wallet.current(generation)) await this.open(id);
  }

  async delete(id) {
    if (!this.wallet.ready || !window.confirm(t('wallet.deleteConfirm'))) return;
    const generation = this.wallet.generation;
    await api(`/history/conversations/${id}`, { method: 'DELETE' });
    if (!this.wallet.current(generation)) return;
    for (const [key, transaction] of this.transactionOutcomes) {
      if (transaction.conversation_id === id) this.transactionOutcomes.delete(key);
    }
    if (id !== this.wallet.conversation) { await this.list(); return; }
    this.wallet.conversation = null;
    this.epoch++;
    this.hooks.clear();
    if (this.showArchived) await this.list();
    else await this.initialize();
  }

  async refreshTransactions(cursor) {
    if (!this.wallet.ready) return;
    const generation = this.wallet.generation;
    const result = await api(`/history/transactions${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
    if (!this.wallet.current(generation) || !this.wallet.ready) return;
    const container = this.nodes['history-transactions'];
    if (!cursor) container.replaceChildren();
    for (const transaction of result.items) {
      this.transactionOutcomes.set(transaction.id, transaction);
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
    this.renderTransactionOutcomes();
  }

  formatTransactionMessage(transaction, success) {
    const parameters = transaction.parameters || {};
    let message = `${t(success ? 'modal.confirmedMsg' : 'modal.revertedMsg')}\n\n**${parameters.amount || ''} ${parameters.token_symbol || 'ETH'}**`;
    if (parameters.recipient) message += `\n${t('modal.recipient')}: \`${parameters.recipient}\``;
    message += `\n**Tx Hash:** \`${transaction.tx_hash || t('wallet.unknownHash')}\``;
    if (parameters.chain_id === 11155111 && /^0x[0-9a-f]{64}$/i.test(transaction.tx_hash || '')) {
      message += `\n[Etherscan](https://sepolia.etherscan.io/tx/${transaction.tx_hash})`;
    }
    return message;
  }

  renderTurnOutcome(turn) {
    const approvalId = turn?.response?.approval_id;
    if (!approvalId) return;
    for (const transaction of this.transactionOutcomes.values()) {
      if (transaction.proposal_id !== approvalId) continue;
      if (transaction.conversation_id !== this.wallet.conversation || transaction.verification_status !== 'MATCHED') continue;
      const success = transaction.receipt_status === 1 && ['MINED_SUCCESS', 'FINALIZED'].includes(transaction.status);
      const reverted = transaction.receipt_status === 0 && ['MINED_REVERTED', 'FINALIZED'].includes(transaction.status);
      if (!success && !reverted) continue;
      const key = `${this.wallet.conversation}:${transaction.id}:${transaction.receipt_status}`;
      if (this.displayedOutcomes.has(key)) continue;
      this.displayedOutcomes.add(key);
      this.hooks.append('agent', this.formatTransactionMessage(transaction, success));
    }
  }

  renderTransactionOutcomes() {
    for (const transaction of this.transactionOutcomes.values()) {
      if (transaction.conversation_id !== this.wallet.conversation || transaction.verification_status !== 'MATCHED') continue;
      const success = transaction.receipt_status === 1 && ['MINED_SUCCESS', 'FINALIZED'].includes(transaction.status);
      const reverted = transaction.receipt_status === 0 && ['MINED_REVERTED', 'FINALIZED'].includes(transaction.status);
      if (!success && !reverted) continue;
      const key = `${this.wallet.conversation}:${transaction.id}:${transaction.receipt_status}`;
      if (this.displayedOutcomes.has(key)) continue;
      this.displayedOutcomes.add(key);
      this.hooks.append('agent', this.formatTransactionMessage(transaction, success));
    }
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
