import { t } from '../i18n.js';

// Policy messages remain unchanged in the API; localize them at the display boundary.
export function guardrailReason(message) {
  const patterns = [
    [/^Invalid EVM address format for recipient: '([\s\S]*)'$/, 'invalidRecipient', m => ({ address: m[1] })],
    [/^Recipient address .* is NOT in the authorized whitelist\.$/, 'recipientNotAllowed'],
    [/^Amount (\S+) ETH exceeds native transfer limit of (\S+) ETH\.$/, 'nativeLimit', m => ({ amount: m[1], limit: m[2] })],
    [/^Amount (\S+) tokens exceeds token policy limit of (\S+) tokens\.$/, 'tokenLimit', m => ({ amount: m[1], limit: m[2] })],
    [/^(Recipient address is required\.|recipient must be a non-empty string|Invalid recipient address)$/, 'recipientRequired'],
    [/^Zero recipient address is not permitted\.$/, 'zeroRecipient'],
    [/^Transaction amount is required\.$/, 'amountRequired'],
    [/^Transaction amount must be strictly greater than 0\.$/, 'positiveAmount'],
    [/^Invalid numerical amount '[\s\S]*$/, 'invalidAmount'],
    [/^Unsupported operation$/, 'unsupportedOperation'],
    [/^Vượt quá hạn mức 24h: DAILY_LIMIT_EXCEEDED$/, 'dailyLimit'],
    [/^Vượt quá hạn mức 24h: PER_TX_LIMIT_EXCEEDED$/, 'perTxLimit'],
    [/^On-chain pre-flight simulation reverted:/, 'simulationFailed'],
  ];
  for (const [pattern, key, parameters] of patterns) {
    const match = String(message).match(pattern);
    if (match) return t(`guardrail.reasons.${key}`, parameters ? parameters(match) : {});
  }
  return t('guardrail.reasons.policyViolation');
}

export function guardrailReasons(data) {
  const statusKeys = {
    ALLOWED: 'allowed', REQUIRE_APP_APPROVAL: 'approvalRequired', CHECK_FAILED: 'checkFailed',
  };
  const key = statusKeys[data.reason_code];
  return key ? [t(`guardrail.reasons.${key}`)] : (data.reasons || []).map(guardrailReason);
}
