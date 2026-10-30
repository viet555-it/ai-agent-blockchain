"""Behavior at the synchronous read, build, simulation and signing boundaries."""

import unittest
from unittest.mock import Mock, patch

from eth_account import Account
from web3.exceptions import TransactionNotFound

from backend.services.blockchain_service import BlockchainService


class BlockchainAdapterTests(unittest.TestCase):
    def setUp(self):
        self.mock_w3 = Mock()
        self.mock_w3.to_checksum_address.side_effect = lambda address: address
        self.service = BlockchainService(w3=self.mock_w3, chain_id=31337, network_manager=Mock())

    def test_native_transfer_fee_modes_keep_exact_wei_and_never_send(self):
        sender = "0x" + "11" * 20
        recipient = "0x" + "22" * 20
        self.mock_w3.eth.get_transaction_count.return_value = 7
        self.mock_w3.eth.gas_price = 9_000_000_000
        for base_fee, priority, expected_priority in (
            (10_000_000_000, "medium", 1_500_000_000),
            (10_000_000_000, "high", 2_000_000_000),
            (None, "medium", None),
        ):
            with self.subTest(base_fee=base_fee, priority=priority):
                self.mock_w3.eth.get_block.return_value = {"baseFeePerGas": base_fee}
                result = self.service.prepare_native_transfer(
                    sender, recipient, "0.000000000000000001", priority
                )
                tx = result["transaction"]
                self.assertEqual(tx["value"], 1)
                self.assertEqual(tx["nonce"], 7)
                self.assertEqual(result["amount_eth"], "0.000000000000000001")
                if base_fee is None:
                    self.assertEqual(tx["gasPrice"], 9_000_000_000)
                    self.assertNotIn("maxFeePerGas", tx)
                    self.assertNotIn("type", tx)
                else:
                    self.assertEqual(tx["maxFeePerGas"], base_fee * 2 + expected_priority)
                    self.assertEqual(tx["maxPriorityFeePerGas"], expected_priority)
                    self.assertNotIn("gasPrice", tx)
        self.mock_w3.eth.send_transaction.assert_not_called()
        self.mock_w3.eth.send_raw_transaction.assert_not_called()

    def test_signing_copies_payload_and_preserves_bound_nonce_and_chain(self):
        # Deterministic test key, independent of credentials in the environment.
        key = "0x" + "01" * 32
        signer_address = Account.from_key(key).address
        self.mock_w3.eth.get_transaction_count.return_value = 9
        self.mock_w3.eth.account.sign_transaction.return_value.raw_transaction = b"signed"
        self.mock_w3.eth.send_raw_transaction.return_value = b"\xaa" * 32
        for bound in (False, True):
            with self.subTest(bound=bound):
                self.mock_w3.eth.get_transaction_count.reset_mock()
                payload = {"from": "0x" + "22" * 20, "to": "0x" + "33" * 20, "value": 1}
                if bound:
                    payload.update(nonce=5, chainId=11155111)
                original = dict(payload)
                tx_hash = self.service.sign_and_send_transaction(payload, key)
                signed_payload = self.mock_w3.eth.account.sign_transaction.call_args.args[0]
                self.assertEqual(payload, original)
                self.assertEqual(signed_payload["from"], signer_address)
                self.assertEqual(signed_payload["nonce"], 5 if bound else 9)
                self.assertEqual(signed_payload["chainId"], 11155111 if bound else 31337)
                self.assertEqual(tx_hash, "aa" * 32)
                if bound:
                    self.mock_w3.eth.get_transaction_count.assert_not_called()
                else:
                    self.mock_w3.eth.get_transaction_count.assert_called_once_with(
                        signer_address, "pending"
                    )
        self.mock_w3.eth.send_raw_transaction.assert_called_with(b"signed")

    def test_signing_broadcast_failure_is_propagated_without_retry(self):
        self.mock_w3.eth.send_raw_transaction.side_effect = TimeoutError("unknown broadcast result")
        with self.assertRaisesRegex(TimeoutError, "unknown broadcast result"):
            self.service.sign_and_send_transaction({"nonce": 1, "chainId": 31337}, "0x" + "01" * 32)
        self.mock_w3.eth.send_raw_transaction.assert_called_once()
        self.mock_w3.eth.wait_for_transaction_receipt.assert_not_called()

    def test_metadata_fallbacks_and_missing_receipt_keep_response_shape(self):
        token = "0x" + "22" * 20
        wallet = "0x" + "33" * 20
        contract = Mock()
        contract.functions.balanceOf.return_value.call.return_value = 10**18 + 1
        for method in ("name", "symbol", "decimals", "totalSupply"):
            getattr(contract.functions, method).return_value.call.side_effect = ValueError(method)
        with patch.object(self.service, "get_erc20_contract", return_value=contract):
            balance = self.service.get_token_balance(token, wallet)
            info = self.service.get_token_info(token)
        self.assertEqual(balance["balance"], "1.000000000000000001")
        self.assertEqual((balance["symbol"], balance["decimals"]), ("TOKEN", 18))
        self.assertEqual(info["name"], "Unknown Token")
        self.assertEqual((info["total_supply"], info["raw_total_supply"]), ("0", 0))
        self.mock_w3.eth.get_transaction_receipt.side_effect = TransactionNotFound("pending")
        self.assertEqual(
            self.service.get_transaction_receipt("0xabc"),
            {"status": "pending", "tx_hash": "0xabc"},
        )

    def test_simulation_manifest_and_spender_use_eth_call_only(self):
        sender, recipient, spender, token = ("0x" + byte * 20 for byte in ("11", "22", "33", "44"))
        manifest = {"contractAddress": token, "runtimeCodeHash": "0x1234"}
        abi = [{"name": "transferFrom"}]
        contract = Mock()
        contract.functions.decimals.return_value.call.return_value = 6
        contract.functions.transferFrom.return_value.call.return_value = False
        self.mock_w3.eth.contract.return_value = contract
        with (
            patch.object(
                self.service.network_manager,
                "load_deployment_manifest",
                return_value=(abi, manifest),
            ),
            patch.object(self.service.network_manager, "verify_contract_bytecode") as verify,
        ):
            result = self.service.simulate_transfer(sender, recipient, "1.000001", spender=spender)
        verify.assert_called_once_with(self.mock_w3, token, "0x1234")
        contract.functions.transferFrom.assert_called_once_with(sender, recipient, 1_000_001)
        contract.functions.transferFrom.return_value.call.assert_called_once_with({"from": spender})
        self.assertFalse(result["isValid"])
        self.assertEqual(result["reason"], "Token operation returned false")
        self.assertEqual(result["raw_amount"], 1_000_001)
        self.mock_w3.eth.send_transaction.assert_not_called()
        self.mock_w3.eth.send_raw_transaction.assert_not_called()
