/** Navigate without reloading the active conversation, forms, or wallet session. */
export function initializeWorkspace() {
  const container = document.querySelector('.app-container');
  const dialog = document.getElementById('settings-dialog');
  const searchToggle = document.getElementById('history-search-toggle');
  searchToggle.addEventListener('click', () => {
    const wrap = document.getElementById('history-search-wrap');
    wrap.hidden = !wrap.hidden;
    searchToggle.setAttribute('aria-expanded', String(!wrap.hidden));
    if (!wrap.hidden) document.getElementById('history-search').focus();
  });
  document.getElementById('history-recent-toggle').addEventListener('click', event => {
    const button = event.currentTarget;
    const list = document.getElementById('conversation-list');
    list.hidden = !list.hidden;
    button.setAttribute('aria-expanded', String(!list.hidden));
  });
  document.getElementById('btn-settings').addEventListener('click', () => dialog.showModal());
  document.getElementById('close-settings').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });

  for (const [side, id] of [['left', 'panel-blockchain'], ['right', 'panel-activity']]) {
    const panel = document.getElementById(id);
    const show = document.getElementById(`show-${side}-panel`);
    const hide = document.querySelector(`[data-hide-panel="${side}"]`);
    const setCollapsed = (collapsed, focus = false) => {
      panel.hidden = collapsed;
      if (side === 'left') show.hidden = !collapsed;
      show.setAttribute('aria-expanded', String(!collapsed));
      container.classList.toggle(`${side}-collapsed`, collapsed);
      if (focus) (collapsed ? show : hide).focus();
    };
    let collapsed = false;
    try { collapsed = localStorage.getItem(`workspace-${side}-collapsed`) === 'true'; } catch { /* Storage may be unavailable. */ }
    setCollapsed(collapsed);
    const toggle = value => {
      setCollapsed(value, true);
      try { localStorage.setItem(`workspace-${side}-collapsed`, String(value)); } catch { /* Keep session controls working. */ }
    };
    hide.addEventListener('click', () => toggle(true));
    show.addEventListener('click', () => toggle(side === 'right' ? !panel.hidden : false));
  }

  const pages = new Map([
    ['chat', document.getElementById('panel-chat')],
    ...['prices', 'guardrails', 'dry-run'].map(name => [name, document.getElementById(`page-${name}`)]),
  ]);
  const navigate = (focus = false) => {
    const requested = location.hash.slice(1);
    const active = pages.has(requested) ? requested : 'chat';
    for (const [name, page] of pages) page.hidden = name !== active;
    // Keep the activity control on the right edge of whichever workspace is open.
    const actions = active === 'chat' ? document.querySelector('.chat-header-actions') : pages.get(active).querySelector('.panel-header');
    actions.appendChild(document.getElementById('show-right-panel'));
    document.querySelectorAll('[data-page-link]').forEach(link => {
      if (link.dataset.pageLink === active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (focus) {
      const target = active === 'chat' ? document.getElementById('chat-input') : document.getElementById(`title-${active}`);
      target.focus({ preventScroll: true });
    }
  };
  window.addEventListener('hashchange', () => navigate(true));
  navigate();
}
