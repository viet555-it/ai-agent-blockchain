import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

globalThis.localStorage = { getItem: () => 'en', setItem() {} };
globalThis.document = { documentElement: {} };
globalThis.fetch = async url => ({ ok: true, json: async () => JSON.parse(await readFile(url, 'utf8')) });
const { initializeI18n, setLanguage } = await import('../i18n.js');
const { guardrailReasons } = await import('../ui/guardrail-reasons.js');
await initializeI18n();

const rejected = { reasons: [
  "Invalid EVM address format for recipient: '0x9965...A4dF'",
  'Amount 8 tokens exceeds token policy limit of 7 tokens.',
  'Vượt quá hạn mức 24h: DAILY_LIMIT_EXCEEDED',
] };

test('guardrail reasons use Vietnamese with exact recipient and amounts', () => {
  setLanguage('vi');
  const reasons = guardrailReasons(rejected);
  assert.match(reasons[0], /Địa chỉ người nhận.*0x9965\.\.\.A4dF/);
  assert.equal(reasons[1], 'Số lượng 8 token vượt hạn mức 7 token mỗi giao dịch.');
  assert.equal(reasons[2], 'Giao dịch vượt phần hạn mức còn lại trong 24 giờ.');
  assert.doesNotMatch(reasons.join(' '), /Invalid EVM|exceeds|DAILY_LIMIT_EXCEEDED/);
});

test('English mode also translates legacy Vietnamese responses', () => {
  setLanguage('en');
  assert.equal(guardrailReasons(rejected)[2], 'The transaction exceeds the remaining 24-hour limit.');
  assert.match(guardrailReasons({ reason_code: 'REQUIRE_APP_APPROVAL' })[0], /^The transaction is valid;/);
  assert.equal(guardrailReasons({ reason_code: 'ALLOWED' })[0], 'The transaction is valid and allowed.');
});

test('unknown policy and request failures have localized messages', () => {
  setLanguage('vi');
  assert.equal(guardrailReasons({ reasons: ['Unexpected backend diagnostic'] })[0],
    'Giao dịch không đáp ứng chính sách bảo vệ hiện tại.');
  assert.equal(guardrailReasons({ reason_code: 'CHECK_FAILED' })[0],
    'Không thể kiểm tra giao dịch lúc này. Vui lòng thử lại.');
});
