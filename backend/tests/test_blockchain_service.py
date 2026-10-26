"""Unit tests for BlockchainService."""
import unittest
from unittest.mock import MagicMock, Mock, patch
from web3.exceptions import ContractLogicError

from backend.services.blockchain_service import BlockchainService


class BlockchainServiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.mock_w3 = Mock()
        self.mock_w3.is_address.side_effect = lambda a: isinstance(a, str) and a.startswith("0x") and len(a) == 42
        self.mock_w3.to_checksum_address.side_effect = lambda a: a
        self.mock_w3.eth.chain_id = 31337

        with patch("backend.services.blockchain_service.Web3.is_address", side_effect=lambda a: isinstance(a, str) and a.startswith("0x") and len(a) == 42):
            self.service = BlockchainService(w3=self.mock_w3, chain_id=31337)

    def test_validate_and_checksum_address(self):
        valid = "0x" + "11" * 20
        with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
            self.assertEqual(self.service.validate_and_checksum_address(valid), valid)

        with patch("backend.services.blockchain_service.Web3.is_address", return_value=False):
            with self.assertRaises(ValueError):
                self.service.validate_and_checksum_address("invalid-address")

    def test_get_native_balance(self):
        addr = "0x" + "11" * 20
        self.mock_w3.eth.get_balance.return_value = 1500000000000000000  # 1.5 ETH
        with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
            res = self.service.get_native_balance(addr)
        self.assertEqual(res["balance"], "1.5")
        self.assertEqual(res["raw_balance"], 1500000000000000000)
        self.assertEqual(res["symbol"], "ETH")

    def test_get_token_balance(self):
        token_addr = "0x" + "22" * 20
        wallet_addr = "0x" + "33" * 20
        mock_contract = Mock()
        mock_contract.functions.balanceOf.return_value.call.return_value = 1000000000000000001
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.symbol.return_value.call.return_value = "AGNT"

        with patch.object(self.service, "get_erc20_contract", return_value=mock_contract):
            with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
                res = self.service.get_token_balance(token_addr, wallet_addr)

        self.assertEqual(res["balance"], "1.000000000000000001")
        self.assertEqual(res["symbol"], "AGNT")
        self.assertEqual(res["decimals"], 18)

    def test_get_token_info(self):
        token_addr = "0x" + "22" * 20
        mock_contract = Mock()
        mock_contract.functions.name.return_value.call.return_value = "Agent Token"
        mock_contract.functions.symbol.return_value.call.return_value = "AGNT"
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.totalSupply.return_value.call.return_value = 1000000 * 10**18

        with patch.object(self.service, "get_erc20_contract", return_value=mock_contract):
            with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
                res = self.service.get_token_info(token_addr)

        self.assertEqual(res["name"], "Agent Token")
        self.assertEqual(res["symbol"], "AGNT")
        self.assertEqual(res["total_supply"], "1000000")

    def test_prepare_native_transfer(self):
        from_addr = "0x" + "11" * 20
        to_addr = "0x" + "22" * 20
        self.mock_w3.eth.get_transaction_count.return_value = 5
        self.mock_w3.eth.gas_price = 20000000000
        self.mock_w3.eth.get_block.return_value = {"baseFeePerGas": 10000000000}

        with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
            prep = self.service.prepare_native_transfer(from_addr, to_addr, "0.5")

        self.assertEqual(prep["type"], "native_transfer")
        self.assertEqual(prep["raw_value"], 500000000000000000)
        self.assertEqual(prep["transaction"]["nonce"], 5)
        self.assertEqual(prep["transaction"]["chainId"], 31337)
        self.assertEqual(prep["transaction"]["type"], "0x2")

    def test_prepare_token_transfer(self):
        token_addr = "0x" + "aa" * 20
        from_addr = "0x" + "11" * 20
        to_addr = "0x" + "22" * 20

        mock_contract = Mock()
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.symbol.return_value.call.return_value = "AGNT"
        mock_contract.encode_abi.return_value = "0xa9059cbb..."
        self.mock_w3.eth.get_transaction_count.return_value = 0
        self.mock_w3.eth.gas_price = 1000000000

        with patch.object(self.service, "get_erc20_contract", return_value=mock_contract):
            with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
                prep = self.service.prepare_token_transfer(token_addr, from_addr, to_addr, "100")

        self.assertEqual(prep["type"], "erc20_transfer")
        self.assertEqual(prep["amount"], "100")
        self.assertEqual(prep["raw_amount"], 100 * 10**18)
        self.assertEqual(prep["token_symbol"], "AGNT")

    def test_simulate_transfer_success(self):
        sender = "0x" + "11" * 20
        recipient = "0x" + "22" * 20
        token_addr = "0x" + "aa" * 20

        mock_contract = Mock()
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.transfer.return_value.call.return_value = True

        with patch.object(self.service, "get_erc20_contract", return_value=mock_contract):
            with patch.object(self.service.network_manager, "verify_contract_bytecode", return_value=True):
                with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
                    res = self.service.simulate_transfer(sender, recipient, "50", token_address=token_addr)

        self.assertTrue(res["isValid"])
        self.assertEqual(res["reason"], "Valid")
        self.assertEqual(res["amount"], "50")

    def test_simulate_transfer_revert(self):
        sender = "0x" + "11" * 20
        recipient = "0x" + "22" * 20
        token_addr = "0x" + "aa" * 20

        mock_contract = Mock()
        mock_contract.functions.decimals.return_value.call.return_value = 18
        mock_contract.functions.transfer.return_value.call.side_effect = ContractLogicError(
            "execution reverted: Amount exceeds guardrail maxTransferLimit"
        )

        with patch.object(self.service, "get_erc20_contract", return_value=mock_contract):
            with patch.object(self.service.network_manager, "verify_contract_bytecode", return_value=True):
                with patch("backend.services.blockchain_service.Web3.is_address", return_value=True):
                    res = self.service.simulate_transfer(sender, recipient, "600", token_address=token_addr)

        self.assertFalse(res["isValid"])
        self.assertIn("Amount exceeds guardrail maxTransferLimit", res["reason"])


if __name__ == "__main__":
    unittest.main()
