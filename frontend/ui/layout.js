/** Keep the header measured and preserve manual chat scroll position. */
export function observeDashboardLayout(state, elements) {
  const header = document.querySelector('.app-header');
  const measureHeader = () => document.documentElement.style.setProperty('--app-header-height', `${header.getBoundingClientRect().height}px`);
  new ResizeObserver(measureHeader).observe(header);
  measureHeader();
  let userScrolling = false;
  let scrollTimer;
  const markUserScroll = () => {
    userScrolling = true;
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => { userScrolling = false; }, 300);
  };
  for (const event of ['wheel', 'touchmove', 'pointerdown']) {
    elements.chatHistory.addEventListener(event, markUserScroll, { passive: true });
  }
  elements.chatHistory.addEventListener('keydown', event => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) markUserScroll();
  });
  elements.chatHistory.addEventListener('scroll', () => {
    if (!userScrolling) return;
    state.followLatest = elements.chatHistory.scrollHeight - elements.chatHistory.scrollTop - elements.chatHistory.clientHeight < 48;
    markUserScroll();
  });
  new ResizeObserver(() => {
    if (state.followLatest) elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
  }).observe(elements.chatHistory);
}
