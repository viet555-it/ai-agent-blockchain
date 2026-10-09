import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from web3 import Web3
from web3.exceptions import ContractLogicError
from backend import example_contract_usage as tools
from backend.token_amounts import to_token_units, format_token_units, UINT256_MAX


class AmountTests(unittest.TestCase):
    def test_exact_amounts_and_large_values(self):
        for value, units in [("1.1", 1100000000000000000), ("1.000000000000000001", 1000000000000000001), ("0.3", 300000000000000000), ("0", 0), (str(UINT256_MAX), UINT256_MAX)]:
            decimals = 0 if units == UINT256_MAX else 18
            self.assertEqual(to_token_units(value, decimals), units)
            self.assertEqual(to_token_units(format_token_units(units, decimals), decimals), units)
        self.assertEqual(to_token_units("1.25", 6), 1250000)
        self.assertEqual(to_token_units("1", 0), 1)

    def test_float_and_bool_are_rejected(self):
        for value in (1.1, True, None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                to_token_units(value, 18)

    def test_invalid_amounts_are_not_truncated(self):
        for value in ("-1", "NaN", "Infinity", "1e3", " 1", "1.0000000000000000001", str(UINT256_MAX + 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                to_token_units(value, 18)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.patch = patch.object(tools, "ABI_DIR", self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)

    def manifest(self, folder=11155111, chain_id=11155111):
        directory = self.base / str(folder)
        directory.mkdir(exist_ok=True)
        (directory / "AgentToken_abi.json").write_text("[]")
        (directory / "deployment.json").write_text(json.dumps({"chainId": str(chain_id), "contractAddress": "0x" + "11" * 20}))

    def test_unknown_chain_does_not_fall_back_to_sepolia(self):
        self.manifest()
        with self.assertRaises(FileNotFoundError): tools.load_contract_info(31337)

    def test_mismatched_manifest_is_rejected(self):
        self.manifest(chain_id=31337)
        with self.assertRaises(ValueError): tools.load_contract_info(11155111)

    def test_no_bytecode_is_rejected(self):
        self.manifest()
        w3 = Mock()
        w3.eth.chain_id = 11155111
        w3.eth.get_code.return_value = b""
        with self.assertRaisesRegex(ValueError, "No contract bytecode"):
            tools.get_agent_token_contract(w3)

    def test_wrong_runtime_hash_is_rejected(self):
        self.manifest()
        p = self.base / "11155111/deployment.json"
        manifest = json.loads(p.read_text()); manifest["runtimeCodeHash"] = "0x" + "00" * 32
        p.write_text(json.dumps(manifest))
        w3 = Mock(); w3.eth.chain_id = 11155111; w3.eth.get_code.return_value = b"code"
        w3.keccak.return_value = Web3.keccak(b"code")
        with self.assertRaisesRegex(ValueError, "does not match"):
            tools.get_agent_token_contract(w3)


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.w3 = Mock(); self.w3.to_checksum_address.side_effect = lambda x: x
        self.contract = Mock(); self.contract.functions.decimals.return_value.call.return_value = 18
        self.mock_contract = patch.object(tools, "get_agent_token_contract", return_value=self.contract)
        self.mock_contract.start(); self.addCleanup(self.mock_contract.stop)

    def test_direct_call_uses_exact_amount_and_sender(self):
        self.contract.functions.transfer.return_value.call.return_value = True
        result = tools.tool_simulate_transfer(self.w3, "sender", "recipient", "1.1")
        self.assertTrue(result["isValid"])
        self.contract.functions.transfer.assert_called_once_with("recipient", 1100000000000000000)
        self.contract.functions.transfer.return_value.call.assert_called_once_with({"from": "sender"})

    def test_transfer_from_simulates_self_spending_and_reverts(self):
        self.contract.functions.transferFrom.return_value.call.side_effect = ContractLogicError("execution reverted")
        result = tools.tool_simulate_transfer(self.w3, "sender", "recipient", "1", spender="sender")
        self.assertFalse(result["isValid"])
        self.contract.functions.transferFrom.return_value.call.assert_called_once_with({"from": "sender"})

    def test_rpc_errors_propagate(self):
        self.contract.functions.transfer.return_value.call.side_effect = ConnectionError("RPC unavailable")
        with self.assertRaises(ConnectionError):
            tools.tool_simulate_transfer(self.w3, "sender", "recipient", "1")

    def test_balance_is_exact_string(self):
        self.contract.functions.balanceOf.return_value.call.return_value = 1000000000000000001
        self.contract.functions.symbol.return_value.call.return_value = "AGNT"
        self.assertEqual(tools.tool_check_balance(self.w3, "sender")["balance"], "1.000000000000000001")


@unittest.skipUnless(os.environ.get("LOCAL_TEST_RPC"), "Set LOCAL_TEST_RPC for local Hardhat integration")
class LocalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w3 = Web3(Web3.HTTPProvider(os.environ["LOCAL_TEST_RPC"]))
        if cls.w3.eth.chain_id != 31337:
            raise RuntimeError("Integration tests are restricted to local chain 31337")
        artifact = json.loads((Path(__file__).resolve().parents[2] / "contracts/artifacts/src/AgentToken.sol/AgentToken.json").read_text())
        cls.owner, cls.spender, cls.recipient = cls.w3.eth.accounts[:3]
        factory = cls.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        receipt = cls.w3.eth.wait_for_transaction_receipt(factory.constructor(cls.owner, 1000000).transact({"from": cls.owner}))
        cls.token = cls.w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])
        cls.temp = tempfile.TemporaryDirectory(); cls.base = Path(cls.temp.name)
        directory = cls.base / "31337"; directory.mkdir()
        (directory / "AgentToken_abi.json").write_text(json.dumps(artifact["abi"]))
        (directory / "deployment.json").write_text(json.dumps({"chainId": "31337", "contractAddress": receipt.contractAddress, "runtimeCodeHash": cls.w3.keccak(cls.w3.eth.get_code(receipt.contractAddress)).hex()}))
        cls.patch = patch.object(tools, "ABI_DIR", cls.base); cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop(); cls.temp.cleanup()

    def test_exact_call_and_allowance_against_real_evm(self):
        self.assertTrue(tools.tool_simulate_transfer(self.w3, self.owner, self.recipient, "1.1")["isValid"])
        self.assertFalse(tools.tool_simulate_transfer(self.w3, self.owner, self.recipient, "1", spender=self.spender)["isValid"])
        self.assertFalse(tools.tool_simulate_transfer(self.w3, self.owner, self.recipient, "1", spender=self.owner)["isValid"])
        tx = self.token.functions.approve(self.spender, 10**18).transact({"from": self.owner})
        self.w3.eth.wait_for_transaction_receipt(tx)
        self.assertTrue(tools.tool_simulate_transfer(self.w3, self.owner, self.recipient, "1", spender=self.spender)["isValid"])
        self.assertFalse(tools.tool_simulate_transfer(self.w3, self.owner, self.recipient, "501")["isValid"])
        self.assertTrue(tools.tool_simulate_transfer(self.w3, self.spender, self.recipient, "0")["isValid"])
        self.assertEqual(tools.tool_check_balance(self.w3, self.owner)["balance"], "1000000")


if __name__ == "__main__":
    unittest.main()
