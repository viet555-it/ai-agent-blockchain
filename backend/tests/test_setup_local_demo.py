"""A stale local manifest must not keep the wallet login broken after setup."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from web3 import Web3
from web3.datastructures import AttributeDict
from web3.exceptions import TransactionNotFound

from scripts import setup_local_demo


class SetupLocalDemoTests(unittest.TestCase):
    def test_reuse_requires_matching_successful_deployment_receipt(self):
        address = "0x" + "12" * 20
        code = b"\x12\x34"
        saved = {
            "chainId": "31337",
            "contractAddress": address,
            "runtimeCodeHash": Web3.to_hex(Web3.keccak(code)),
            "transactionHash": "0x" + "34" * 32,
        }
        cases = {
            "valid": ({"status": 1, "contractAddress": address}, True),
            "missing": (TransactionNotFound("missing"), False),
            "reverted": ({"status": 0, "contractAddress": address}, False),
            "other_contract": ({"status": 1, "contractAddress": "0x" + "56" * 20}, False),
            "legacy_without_hash": (None, False),
        }
        for name, (receipt, reusable) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                artifact = root / "contracts/artifacts/src/AgentToken.sol/AgentToken.json"
                artifact.parent.mkdir(parents=True)
                artifact.write_text(json.dumps({"abi": [], "bytecode": "0x1234"}))
                destination = root / "backend/abi/31337"
                destination.mkdir(parents=True)
                manifest = dict(saved)
                if name == "legacy_without_hash":
                    manifest.pop("transactionHash")
                (destination / "deployment.json").write_text(json.dumps(manifest))
                (destination / "AgentToken_abi.json").write_text("[]")
                w3 = MagicMock()
                w3.eth.chain_id = 31337
                w3.client_version = "HardhatNetwork"
                w3.eth.get_code.return_value = code
                w3.keccak.side_effect = Web3.keccak
                w3.eth.accounts = [address]
                if isinstance(receipt, Exception):
                    w3.eth.get_transaction_receipt.side_effect = receipt
                else:
                    w3.eth.get_transaction_receipt.return_value = receipt
                w3.eth.wait_for_transaction_receipt.return_value = AttributeDict({
                    "status": 1, "contractAddress": address, "transactionHash": b"\x78" * 32,
                })
                with (
                    patch.object(setup_local_demo, "ROOT", root),
                    patch.object(setup_local_demo, "Web3", wraps=Web3) as web3_class,
                ):
                    web3_class.return_value = w3
                    result = setup_local_demo.setup("http://127.0.0.1:8545")
                self.assertEqual(result["status"], "reused" if reusable else "deployed")
                self.assertEqual(w3.eth.contract.called, not reusable)
                exported = json.loads((destination / "deployment.json").read_text())
                self.assertEqual(exported["transactionHash"], result["transactionHash"])
