"""Real wallet/ledger workflows over temporary SQLite and a no-network chain fixture."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import select
from web3 import Web3

from backend.db.schema_limits_v2 import entries
from backend.db.schema_v1 import (
    approvals,
    attempts,
    contexts,
    conversations,
    deployments,
    proposals,
    send_locks,
    sessions,
    wallets,
)
from backend.db.store import Database
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.daily_limits import DailyLimitService, LimitScope
from backend.services.wallet.proposals import WalletProposals
from backend.services.wallet.submissions import WalletSubmissions
from backend.services.wallet_common import Principal
from backend.token_amounts import UINT256_MAX, format_token_units, to_token_units
from backend.wallet_settings import WalletSettings

SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
TOKEN = "0x1111111111111111111111111111111111111111"


class SafetyRuntime:
    def __init__(self, path, case):
        self.case, self.fixture = case, case["fixture"]
        self.db = Database("sqlite:///" + path.as_posix())
        self.db.migrate()
        native = self.fixture["assets"]["native"]
        token = self.fixture["assets"]["erc20:" + TOKEN]
        self.config = PolicyConfig(
            max_native_transfer_limit=Decimal(format_token_units(int(native["per_tx"]), 18)),
            max_daily_native_transfer_limit=Decimal(format_token_units(int(native["daily"]), 18)),
            max_token_transfer_limit=Decimal(
                format_token_units(int(token["per_tx"]), token["decimals"])
            ),
            max_daily_token_transfer_limit=Decimal(
                format_token_units(int(token["daily"]), token["decimals"])
            ),
            recipient_whitelist=self.fixture["recipient_whitelist"],
            enforce_whitelist=self.fixture["enforce_whitelist"],
            require_human_approval_for_writes=self.fixture["require_app_approval"],
        )
        self.policy = PolicyEngine(self.config)
        self.chain = self._chain(token["decimals"])
        self.principal = Principal("fixture-session", self.fixture["wallet_id"], SENDER)
        self.scope = {
            "principal": self.principal,
            "context_id": "fixture-context",
            "generation": 1,
            "conversation_id": "fixture-conversation",
        }
        self.deployment = SimpleNamespace(deployment=lambda: self.fixture["deployment_id"])
        settings = WalletSettings(str(self.db.engine.url), browser_writes=True)
        self.wallet = WalletProposals(self.db, settings, self.chain, self.policy, self.deployment)
        self.submissions = WalletSubmissions(
            self.db, settings, self.chain, self.policy, self.deployment, self.wallet
        )
        self.authorization_calls = 0
        self.authorizations = 0
        self._seed()

    def _chain(self, decimals):
        chain = MagicMock()
        chain.chain_id = chain.w3.eth.chain_id = 31337
        chain.rpc_url = "http://127.0.0.1:1"
        chain.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        chain.network_manager.load_deployment_manifest.return_value = (
            [],
            {"contractAddress": TOKEN, "runtimeCodeHash": "0x" + "11" * 32},
        )
        chain.network_manager.verify_contract_bytecode.return_value = True
        chain.w3.eth.block_number = 10
        chain.w3.eth.get_transaction_count.return_value = 0
        chain.w3.eth.get_balance.return_value = 10**30
        chain.w3.eth.estimate_gas.return_value = 21000
        chain.get_token_info.return_value = {"decimals": decimals, "symbol": "AGNT"}
        chain.get_native_balance.return_value = {
            "address": SENDER,
            "balance": "100",
            "raw_balance": str(100 * 10**18),
            "symbol": "ETH",
        }

        def transaction(sender, recipient, value, data="0x"):
            return {
                "transaction": {
                    "from": sender,
                    "to": recipient,
                    "value": value,
                    "data": data,
                    "nonce": 0,
                    "chainId": 31337,
                    "gas": 100000,
                    "gasPrice": 10**9,
                }
            }

        chain.prepare_native_transfer.side_effect = lambda sender, recipient, amount: transaction(
            sender, recipient, to_token_units(amount, 18)
        )
        chain.prepare_token_transfer.side_effect = lambda contract, sender, recipient, amount: (
            transaction(
                sender,
                contract,
                0,
                "0xa9059cbb"
                + recipient[2:].lower().rjust(64, "0")
                + hex(to_token_units(amount, decimals))[2:].rjust(64, "0"),
            )
        )
        chain.w3.eth.send_transaction.side_effect = RuntimeError(
            "Broadcast forbidden in safety evaluation"
        )
        chain.w3.eth.send_raw_transaction.side_effect = RuntimeError(
            "Broadcast forbidden in safety evaluation"
        )
        return chain

    def _seed(self):
        now = self.fixture["now_utc_epoch"]
        with self.db.transaction() as c:
            c.execute(
                wallets.insert().values(id=self.principal.wallet_id, address=SENDER, created_at=now)
            )
            c.execute(
                sessions.insert().values(
                    id=self.principal.session_id,
                    wallet_id=self.principal.wallet_id,
                    token_hash="a" * 64,
                    csrf_hash="b" * 64,
                    created_at=now,
                    expires_at=now + 3600,
                )
            )
            c.execute(
                deployments.insert().values(
                    id=self.fixture["deployment_id"],
                    chain_id=31337,
                    fingerprint="c" * 64,
                    details={},
                    active=True,
                    created_at=now,
                )
            )
            c.execute(
                contexts.insert().values(
                    id=self.scope["context_id"],
                    session_id=self.principal.session_id,
                    deployment_id=self.fixture["deployment_id"],
                    generation=1,
                )
            )
            c.execute(
                conversations.insert().values(
                    id=self.scope["conversation_id"],
                    wallet_id=self.principal.wallet_id,
                    deployment_id=self.fixture["deployment_id"],
                    title="Safety fixture",
                    created_at=now,
                    updated_at=now,
                    lease_until=0,
                )
            )
            c.execute(
                send_locks.insert().values(
                    id="fixture-lock",
                    wallet_id=self.principal.wallet_id,
                    deployment_id=self.fixture["deployment_id"],
                )
            )
            for index, row in enumerate(self.fixture["spent"] + self.fixture["reservations"]):
                scope = LimitScope(
                    self.principal.wallet_id, self.fixture["deployment_id"], row["asset_id"]
                )
                reservation_id = f"fixture-usage-{index}"
                ledger = DailyLimitService()
                ledger.reserve(
                    c,
                    scope,
                    reservation_id,
                    row["amount_base_units"],
                    per_tx_limit=UINT256_MAX,
                    daily_limit=UINT256_MAX,
                    now=row.get("created_at", now),
                )
                if "block_timestamp" in row:
                    ledger.settle_success(
                        c, reservation_id, block_timestamp=row["block_timestamp"], now=now
                    )

    def snapshot(self):
        with self.db.transaction() as c:
            return {
                table.name: [dict(row) for row in c.execute(select(table)).mappings()]
                for table in (entries, proposals, attempts, approvals)
            }

    def prepare(self):
        request = self.case["request"]
        asset = self.fixture["assets"][request["asset_id"]]
        return self.wallet.prepare(
            self.scope,
            request["operation"],
            format_token_units(int(request["amount_base_units"]), asset["decimals"]),
            request["recipient"],
        )

    def authorize(self, pending, parameter_hash=None):
        self.authorization_calls += 1
        result = self.submissions.authorize(
            self.principal,
            pending.approval_id,
            self.scope["context_id"],
            1,
            parameter_hash or pending.parameter_hash,
        )
        self.authorizations += 1
        return result

    @property
    def broadcast_attempts(self):
        return (
            self.chain.w3.eth.send_transaction.call_count
            + self.chain.w3.eth.send_raw_transaction.call_count
        )

    def close(self):
        self.db.close()
