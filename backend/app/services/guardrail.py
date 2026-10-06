from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal
import datetime
from web3 import Web3
from app.core.config import settings

class GuardrailPolicyEngine:
    def __init__(self):
        self.max_eth_limit = Decimal(str(settings.GUARDRAIL_MAX_ETH_TRANSFER))
        self.max_token_limit = Decimal(str(settings.GUARDRAIL_MAX_TOKEN_TRANSFER))
        self.whitelist = {addr.lower() for addr in settings.GUARDRAIL_WHITELIST}
        self.blacklist = {addr.lower() for addr in settings.GUARDRAIL_BLACKLIST}
        self.require_human_approval = settings.GUARDRAIL_REQUIRE_HUMAN_APPROVAL
        self.simulation_enabled = settings.GUARDRAIL_SIMULATION_ENABLED
        self.audit_logs: List[Dict[str, Any]] = []

    def evaluate_transaction(
        self,
        tx_type: str,
        to_address: str,
        value_eth: Optional[str] = "0",
        token_amount: Optional[str] = "0",
        sender_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates write transaction requests against safety policies (Limits, Whitelist, Blacklist).
        Returns detailed safety report with status (ALLOWED, BLOCKED, WARNING).
        """
        timestamp = datetime.datetime.now().isoformat()
        clean_to = to_address.lower().strip()
        
        checks = []
        is_blocked = False
        block_reason = None
        warnings = []

        # 1. Address Format & Blacklist Check
        if not Web3.is_address(to_address):
            is_blocked = True
            block_reason = f"Địa chỉ nhận không hợp lệ: {to_address}"
            checks.append({"name": "Format Check", "status": "FAILED", "detail": "Invalid address hex / checksum format"})
        elif clean_to in self.blacklist:
            is_blocked = True
            block_reason = "Địa chỉ nhận nằm trong danh sách đen (Blacklist / Burn Address) có rủi ro cao!"
            checks.append({"name": "Blacklist Check", "status": "FAILED", "detail": "Target address is blacklisted"})
        else:
            checks.append({"name": "Address Validation", "status": "PASSED", "detail": "Valid EVM address format"})

        # 2. Whitelist Check (Warning if unknown address, but allowed with human confirmation)
        if clean_to in self.whitelist:
            checks.append({"name": "Whitelist Check", "status": "PASSED", "detail": "Address is in trusted whitelist"})
        else:
            checks.append({"name": "Whitelist Check", "status": "INFO", "detail": "Address not in whitelist, manual confirmation required"})

        # 3. Transaction Amount Limit Check
        if tx_type == "transfer_native" and value_eth:
            amount_dec = Decimal(str(value_eth))
            if amount_dec > self.max_eth_limit:
                is_blocked = True
                block_reason = f"Số lượng gửi ({amount_dec} ETH) vượt quá hạn mức an toàn cho phép ({self.max_eth_limit} ETH/giao dịch)!"
                checks.append({"name": "Limit Policy", "status": "FAILED", "detail": f"Amount {amount_dec} ETH > Max limit {self.max_eth_limit} ETH"})
            else:
                checks.append({"name": "Limit Policy", "status": "PASSED", "detail": f"Amount {amount_dec} ETH within limit ({self.max_eth_limit} ETH)"})

        elif tx_type == "transfer_token" and token_amount:
            amount_dec = Decimal(str(token_amount))
            if amount_dec > self.max_token_limit:
                is_blocked = True
                block_reason = f"Số lượng token ({amount_dec}) vượt quá hạn mức an toàn ({self.max_token_limit})!"
                checks.append({"name": "Token Limit Policy", "status": "FAILED", "detail": f"Amount {amount_dec} > Max limit {self.max_token_limit}"})
            else:
                checks.append({"name": "Token Limit Policy", "status": "PASSED", "detail": f"Amount {amount_dec} within limit ({self.max_token_limit})"})

        # 4. Human-In-The-Loop Check
        human_approval_required = self.require_human_approval

        result_status = "BLOCKED" if is_blocked else "ALLOWED"
        
        log_entry = {
            "id": f"guard_{len(self.audit_logs) + 1}",
            "timestamp": timestamp,
            "tx_type": tx_type,
            "target": to_address,
            "value_eth": value_eth,
            "status": result_status,
            "block_reason": block_reason,
            "checks": checks,
            "human_approval_required": human_approval_required
        }
        self.audit_logs.append(log_entry)

        return {
            "status": result_status,
            "is_safe": not is_blocked,
            "block_reason": block_reason,
            "checks": checks,
            "human_approval_required": human_approval_required,
            "timestamp": timestamp
        }

    def get_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self.audit_logs[-limit:]))

    def get_policies(self) -> Dict[str, Any]:
        return {
            "max_eth_limit": float(self.max_eth_limit),
            "max_token_limit": float(self.max_token_limit),
            "whitelist_count": len(self.whitelist),
            "blacklist_count": len(self.blacklist),
            "human_approval_required": self.require_human_approval,
            "simulation_enabled": self.simulation_enabled,
            "whitelist": list(self.whitelist)
        }

    def update_policies(self, max_eth: Optional[float] = None, max_token: Optional[float] = None) -> None:
        if max_eth is not None and max_eth > 0:
            self.max_eth_limit = Decimal(str(max_eth))
        if max_token is not None and max_token > 0:
            self.max_token_limit = Decimal(str(max_token))

guardrail_engine = GuardrailPolicyEngine()

