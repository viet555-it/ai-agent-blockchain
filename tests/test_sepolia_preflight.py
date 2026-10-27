"""Read-only preflight gates with a fake RPC; no credentials or network."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from web3 import Web3

from scripts.preflight_sepolia import ReadOnlyHTTPProvider, preflight

ADDRESS = "0x" + "11" * 20
WALLET = "0x" + "22" * 20


class SepoliaPreflightTests(unittest.TestCase):
    def test_rpc_guard_blocks_broadcast_after_middleware_has_been_cached(self):
        provider = ReadOnlyHTTPProvider("https://fixture.invalid")
        w3 = Web3(provider)
        with patch.object(
            Web3.HTTPProvider,
            "make_request",
            return_value={"jsonrpc": "2.0", "id": 1, "result": "0xaa"},
        ) as transport:
            self.assertEqual(w3.eth.chain_id, 170)
            self.assertEqual(w3.eth.block_number, 170)
            with self.assertRaisesRegex(RuntimeError, "read-only"):
                w3.manager.request_blocking("eth_sendRawTransaction", ["0xdead"])
            self.assertEqual(transport.call_count, 2)
        self.assertEqual(provider.methods["eth_chainId"], 1)
        self.assertEqual(provider.methods["eth_blockNumber"], 1)
        self.assertEqual(provider.denied, ["eth_sendRawTransaction"])

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        folder = self.root / "backend/abi/11155111"
        folder.mkdir(parents=True)
        abi_text = "[]\n"
        (folder / "AgentToken_abi.json").write_text(abi_text)
        self.code = b"test-contract-code"
        self.manifest = {
            "chainId": "11155111",
            "contractAddress": ADDRESS,
            "deployer": WALLET,
            "runtimeCodeHash": Web3.to_hex(Web3.keccak(self.code)),
        }
        self.manifest_path = folder / "deployment.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        (self.root / "knowledge").mkdir()
        self.scope = {
            "chain_id": 11155111,
            "contract_address": ADDRESS,
            "abi_hash": "sha256:" + hashlib.sha256(abi_text.encode()).hexdigest(),
            "doc_version": "test-v1",
        }
        self.scope_path = self.root / "knowledge/manifest.json"
        self.scope_path.write_text(json.dumps({"deployment_scope": self.scope}))
        self.w3 = MagicMock()
        eth = self.w3.eth
        eth.chain_id = 11155111
        eth.get_block.return_value = {"number": 100, "hash": b"\xaa" * 32, "timestamp": 1000}
        eth.get_code.return_value = self.code
        eth.get_balance.return_value = 10**17
        eth.gas_price = 1000000
        eth.get_transaction_count.return_value = 2
        self.functions = eth.contract.return_value.functions
        for name, value in {
            "name": "Agent Token",
            "symbol": "AGNT",
            "decimals": 18,
            "owner": WALLET,
            "totalSupply": 1000000 * 10**18,
            "cap": 10000000 * 10**18,
            "maxTransferLimit": 500 * 10**18,
            "FAUCET_AMOUNT_LIMIT": 100 * 10**18,
            "faucetCooldown": 60,
            "lastFaucetClaim": 980,
            "balanceOf": 123 * 10**18 + 1,
        }.items():
            getattr(self.functions, name).return_value.call.return_value = value

    def tearDown(self):
        self.w3.eth.send_transaction.assert_not_called()
        self.w3.eth.send_raw_transaction.assert_not_called()
        self.w3.eth.account.sign_transaction.assert_not_called()

    def test_success_pins_reads_and_preserves_exact_units_without_write_authorization(self):
        result = preflight(self.root, self.w3)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["write_authorized"])
        self.assertEqual(result["facts"]["observer_token_balance"], "123.000000000000000001")
        self.assertEqual(result["facts"]["observer_faucet_wait_seconds"], 40)
        self.w3.eth.get_balance.assert_called_once_with(WALLET, block_identifier=100)
        self.functions.faucetCooldown.return_value.call.assert_called_once_with(
            block_identifier=100
        )

    def test_wrong_chain_never_reads_contract(self):
        self.w3.eth.chain_id = 1
        result = preflight(self.root, self.w3)
        self.assertEqual(result["status"], "FAIL")
        self.w3.eth.get_code.assert_not_called()
        self.w3.eth.contract.assert_not_called()

    def test_empty_or_wrong_bytecode_blocks_contract_reads(self):
        for code in [b"", b"wrong"]:
            with self.subTest(code=code):
                self.w3.eth.get_code.return_value = code
                self.assertEqual(preflight(self.root, self.w3)["status"], "FAIL")
                self.w3.eth.contract.assert_not_called()

    def test_rag_scope_or_abi_mismatch_blocks_rpc(self):
        for field, value in [("chain_id", 1), ("contract_address", WALLET), ("abi_hash", "wrong")]:
            with self.subTest(field=field):
                self.scope_path.write_text(
                    json.dumps({"deployment_scope": {**self.scope, field: value}})
                )
                self.assertEqual(preflight(self.root, self.w3)["status"], "FAIL")
                self.w3.eth.get_block.assert_not_called()

    def test_transport_error_never_exposes_rpc_key(self):
        self.w3.eth.get_block.side_effect = ConnectionError("https://rpc.invalid/secret-key")
        result = preflight(self.root, self.w3)
        self.assertEqual(result["failure"]["stage"], "rpc_chain")
        self.assertNotIn("secret-key", json.dumps(result))

    def test_observer_does_not_become_a_signer(self):
        observer = "0x" + "33" * 20
        result = preflight(self.root, self.w3, wallet=observer)
        self.assertEqual(result["facts"]["observed_wallet"], observer)
        self.assertFalse(result["write_authorized"])
