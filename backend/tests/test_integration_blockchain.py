"""Live EVM integration tests for BlockchainService and NetworkManager."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from web3 import Web3

from backend.network.config import ChainConfig, NativeCurrency
from backend.network.network_manager import NetworkManager
from backend.services.blockchain_service import BlockchainService
from backend.token_amounts import to_token_units

TEST_RPC_URL = os.environ.get("LOCAL_TEST_RPC", "http://127.0.0.1:8545")


def is_rpc_available(url: str) -> bool:
    try:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 1.0}))
        return w3.is_connected() and w3.eth.chain_id == 31337
    except Exception:
        return False


RPC_AVAILABLE = is_rpc_available(TEST_RPC_URL)


@unittest.skipUnless(
    RPC_AVAILABLE or os.environ.get("RUN_INTEGRATION_TESTS"),
    f"Local Hardhat EVM not detected on {TEST_RPC_URL}. Start a node with 'npm run node' in contracts/ or set LOCAL_TEST_RPC.",
)
class BlockchainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w3 = Web3(Web3.HTTPProvider(TEST_RPC_URL))
        if cls.w3.eth.chain_id != 31337:
            raise RuntimeError(f"Expected chain 31337, got {cls.w3.eth.chain_id}")

        cls.owner = cls.w3.eth.accounts[0]
        cls.spender = cls.w3.eth.accounts[1]
        cls.recipient = cls.w3.eth.accounts[2]
        cls.user3 = cls.w3.eth.accounts[3]

        # Load compiled AgentToken artifact
        artifact_path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "artifacts"
            / "src"
            / "AgentToken.sol"
            / "AgentToken.json"
        )
        if not artifact_path.exists():
            raise FileNotFoundError(f"Contract artifact not found at {artifact_path}. Run 'npm run compile' first.")

        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        cls.abi = artifact["abi"]
        cls.bytecode = artifact["bytecode"]

        # Deploy fresh AgentToken with 1,000,000 supply
        factory = cls.w3.eth.contract(abi=cls.abi, bytecode=cls.bytecode)
        tx_hash = factory.constructor(cls.owner, 1_000_000).transact({"from": cls.owner})
        receipt = cls.w3.eth.wait_for_transaction_receipt(tx_hash)
        cls.contract_address = receipt.contractAddress

        # Set up temporary directory with manifest and ABI for NetworkManager
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.manifest_dir = Path(cls.temp_dir.name) / "31337"
        cls.manifest_dir.mkdir(parents=True)

        (cls.manifest_dir / "AgentToken_abi.json").write_text(json.dumps(cls.abi), encoding="utf-8")
        runtime_hash = cls.w3.keccak(cls.w3.eth.get_code(cls.contract_address)).hex()
        (cls.manifest_dir / "deployment.json").write_text(
            json.dumps(
                {
                    "chainId": "31337",
                    "contractAddress": cls.contract_address,
                    "runtimeCodeHash": runtime_hash,
                }
            ),
            encoding="utf-8",
        )

        # Create NetworkManager and BlockchainService
        cls.network_config = ChainConfig(
            chain_id=31337,
            name="Hardhat Localhost",
            rpc_urls=[TEST_RPC_URL],
            native_currency=NativeCurrency(name="Local Ether", symbol="ETH", decimals=18),
            is_testnet=True,
        )
        cls.network_manager = NetworkManager({31337: cls.network_config})
        cls.network_manager._networks[31337] = cls.network_config

        # Monkey patch search dirs for test manifest
        from backend.network import network_manager as nm_mod

        cls._orig_backend_abi_dir = nm_mod.BACKEND_ABI_DIR
        nm_mod.BACKEND_ABI_DIR = Path(cls.temp_dir.name)

        cls.service = BlockchainService(w3=cls.w3, chain_id=31337, network_manager=cls.network_manager)
        cls.token = cls.w3.eth.contract(address=cls.contract_address, abi=cls.abi)

    @classmethod
    def tearDownClass(cls):
        from backend.network import network_manager as nm_mod

        nm_mod.BACKEND_ABI_DIR = cls._orig_backend_abi_dir
        cls.temp_dir.cleanup()

    def test_01_network_health_check(self):
        health = self.network_manager.check_rpc_health(TEST_RPC_URL, 31337)
        self.assertTrue(health.is_healthy)
        self.assertGreater(health.block_number, 0)
        self.assertGreater(health.latency_ms, 0)
        self.assertIsNone(health.error)

    def test_02_native_balance_and_token_info(self):
        # Native balance check
        owner_native = self.service.get_native_balance(self.owner)
        self.assertEqual(owner_native["symbol"], "ETH")
        self.assertGreater(owner_native["raw_balance"], 0)

        # Token info check
        token_info = self.service.get_token_info(self.contract_address)
        self.assertEqual(token_info["name"], "Agent Token")
        self.assertEqual(token_info["symbol"], "AGNT")
        self.assertEqual(token_info["decimals"], 18)
        self.assertEqual(token_info["total_supply"], "1000000")

        # Initial owner token balance
        owner_token = self.service.get_token_balance(self.contract_address, self.owner)
        self.assertEqual(owner_token["balance"], "1000000")

    def test_03_faucet_claim_and_cooldown(self):
        # Claim 50 AGNT for recipient
        claim_tx = self.token.functions.faucet(50 * 10**18).transact({"from": self.recipient})
        self.w3.eth.wait_for_transaction_receipt(claim_tx)

        recipient_bal = self.service.get_token_balance(self.contract_address, self.recipient)
        self.assertEqual(recipient_bal["balance"], "50")

        # Second claim immediately must fail cooldown
        with self.assertRaises(Exception):
            fail_tx = self.token.functions.faucet(10 * 10**18).transact({"from": self.recipient})
            self.w3.eth.wait_for_transaction_receipt(fail_tx)

    def test_04_simulate_transfer_guardrails(self):
        # 1. Allowed transfer within maxTransferLimit (<= 500 AGNT)
        sim_ok = self.service.simulate_transfer(
            sender=self.owner,
            recipient=self.recipient,
            amount_token="250.5",
            token_address=self.contract_address,
        )
        self.assertTrue(sim_ok["isValid"])
        self.assertEqual(sim_ok["reason"], "Valid")
        self.assertEqual(sim_ok["amount"], "250.5")

        # 2. Rejection when exceeding maxTransferLimit (> 500 AGNT)
        sim_limit = self.service.simulate_transfer(
            sender=self.owner,
            recipient=self.recipient,
            amount_token="501",
            token_address=self.contract_address,
        )
        self.assertFalse(sim_limit["isValid"])
        self.assertTrue(
            "AgentToken: Transfer exceeds max limit" in sim_limit["reason"]
            or "exceeds" in sim_limit["reason"].lower()
        )

        # 3. Rejection when balance is insufficient
        sim_insufficient = self.service.simulate_transfer(
            sender=self.user3,  # user3 has 0 balance
            recipient=self.recipient,
            amount_token="10",
            token_address=self.contract_address,
        )
        self.assertFalse(sim_insufficient["isValid"])
        self.assertTrue(
            "ERC20InsufficientBalance" in sim_insufficient["reason"]
            or "insufficient" in sim_insufficient["reason"].lower()
        )


    def test_05_real_transfer_within_limit_and_over_limit(self):
        # Transfer 200 AGNT from owner to user3
        prep = self.service.prepare_token_transfer(
            token_address=self.contract_address,
            from_address=self.owner,
            to_address=self.user3,
            amount_token="200",
        )
        self.assertEqual(prep["amount"], "200")

        # Execute tx from owner
        tx_hash = self.token.functions.transfer(self.user3, 200 * 10**18).transact({"from": self.owner})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        self.assertEqual(receipt.status, 1)

        bal_user3 = self.service.get_token_balance(self.contract_address, self.user3)
        self.assertEqual(bal_user3["balance"], "200")

        # Attempt to transfer 600 AGNT directly on-chain -> reverts
        with self.assertRaises(Exception):
            revert_tx = self.token.functions.transfer(self.user3, 600 * 10**18).transact({"from": self.owner})
            self.w3.eth.wait_for_transaction_receipt(revert_tx)

    def test_06_allowance_and_transfer_from(self):
        # Check initial allowance
        allowance = self.service.get_allowance(self.contract_address, self.owner, self.spender)
        self.assertEqual(allowance["allowance"], "0")

        # Approve 300 AGNT
        tx_app = self.token.functions.approve(self.spender, 300 * 10**18).transact({"from": self.owner})
        self.w3.eth.wait_for_transaction_receipt(tx_app)

        allowance_after = self.service.get_allowance(self.contract_address, self.owner, self.spender)
        self.assertEqual(allowance_after["allowance"], "300")

        # Spender executes transferFrom 100 AGNT to user3
        tx_from = self.token.functions.transferFrom(self.owner, self.user3, 100 * 10**18).transact(
            {"from": self.spender}
        )
        receipt_from = self.w3.eth.wait_for_transaction_receipt(tx_from)
        self.assertEqual(receipt_from.status, 1)

        # Allowance consumed to 200
        allowance_consumed = self.service.get_allowance(self.contract_address, self.owner, self.spender)
        self.assertEqual(allowance_consumed["allowance"], "200")

    def test_07_guardrail_admin_update_limit(self):
        # Update limit to 1500 AGNT
        tx_limit = self.token.functions.setMaxTransferLimit(1500 * 10**18).transact({"from": self.owner})
        self.w3.eth.wait_for_transaction_receipt(tx_limit)

        # Previously rejected 600 AGNT simulation now passes!
        sim_new = self.service.simulate_transfer(
            sender=self.owner,
            recipient=self.user3,
            amount_token="600",
            token_address=self.contract_address,
        )
        self.assertTrue(sim_new["isValid"])
        self.assertEqual(sim_new["reason"], "Valid")


if __name__ == "__main__":
    unittest.main()
