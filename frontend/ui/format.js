/** Text formatting shared by dashboard views. */
export function shortenAddress(addr) {
  if (!addr || addr.length < 10) return addr || '0x...';
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

export function formatMarkdown(text) {
  if (!text) return '';
  let formatted = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Bold
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Inline code
  formatted = formatted.replace(/`([^`]+)`/g, '<code class="mono">$1</code>');
  // Block quotes
  formatted = formatted.replace(/^>\s*(.*?)$/gm, '<blockquote>$1</blockquote>');
  // Newlines
  formatted = formatted.replace(/\n/g, '<br>');

  return formatted;
}
