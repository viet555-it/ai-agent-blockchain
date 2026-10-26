"""Unit and integration tests for NetworkManager."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.network.config import ChainConfig, NativeCurrency
from backend.network.network_manager import NetworkHealth, NetworkManager


class NetworkManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = NetworkManager()

    def test_default_networks_registered(self):
        networks = self.manager.list_networks()
        chain_ids = [n["chain_id"] for n in networks]
        self.assertIn(31337, chain_ids)
        self.assertIn(11155111, chain_ids)

    def test_switch_network(self):
        self.assertEqual(self.manager.active_chain_id, 31337)
        self.manager.set_active_chain_id(11155111)
        self.assertEqual(self.manager.active_chain_id, 11155111)

    def test_switch_to_unregistered_network_raises_error(self):
        with self.assertRaises(ValueError):
            self.manager.set_active_chain_id(999999)

    def test_register_custom_network(self):
        custom = ChainConfig(
            chain_id=137,
            name="Polygon Mainnet",
            rpc_urls=["https://polygon-rpc.com"],
            native_currency=NativeCurrency(name="Polygon", symbol="POL", decimals=18),
            is_testnet=False,
        )
        self.manager.register_network(custom)
        config = self.manager.get_network_config(137)
        self.assertEqual(config.name, "Polygon Mainnet")
        self.assertEqual(config.native_currency.symbol, "POL")

    def test_rpc_health_check_offline(self):
        health = self.manager.check_rpc_health("http://127.0.0.1:54321", 31337, timeout=0.5)
        self.assertFalse(health.is_healthy)
        self.assertIsNotNone(health.error)
        self.assertEqual(health.to_dict()["status"], "UNREACHABLE")

    def test_rpc_health_check_mismatched_chain_id(self):
        with patch("backend.network.network_manager.Web3") as mock_web3_cls:
            mock_w3 = Mock()
            mock_w3.is_connected.return_value = True
            mock_w3.eth.chain_id = 1
            mock_web3_cls.return_value = mock_w3

            health = self.manager.check_rpc_health("http://fake-rpc:8545", 11155111)
            self.assertFalse(health.is_healthy)
            self.assertIn("Chain ID mismatch", health.error)

    def test_rpc_failover_selects_first_healthy(self):
        custom = ChainConfig(
            chain_id=11155111,
            name="Sepolia",
            rpc_urls=["https://rpc1", "https://rpc2"],
        )
        mgr = NetworkManager({11155111: custom})
        with patch.object(mgr, "check_rpc_health") as mock_health:
            # First RPC fails, second succeeds
            mock_health.side_effect = [
                NetworkHealth(11155111, "https://rpc1", False, 100, error="Timeout"),
                NetworkHealth(11155111, "https://rpc2", True, 45, block_number=1000),
            ]
            with patch("backend.network.network_manager.Web3") as mock_w3_cls:
                mock_w3 = Mock()
                mock_w3_cls.return_value = mock_w3
                w3, url = mgr.get_healthy_provider(11155111)
                self.assertEqual(url, "https://rpc2")


    def test_all_rpcs_failing_raises_connection_error(self):
        with patch.object(self.manager, "check_rpc_health") as mock_health:
            mock_health.return_value = NetworkHealth(31337, "http://localhost", False, 100, error="Offline")
            with self.assertRaises(ConnectionError):
                self.manager.get_healthy_provider(31337)

    def test_verify_contract_bytecode(self):
        w3 = Mock()
        w3.to_checksum_address.side_effect = lambda x: x
        w3.eth.get_code.return_value = b""
        with self.assertRaisesRegex(ValueError, "No contract bytecode found"):
            self.manager.verify_contract_bytecode(w3, "0x1111111111111111111111111111111111111111")

        # Test valid bytecode and hash
        code = b"\x60\x80\x60\x40"
        w3.eth.get_code.return_value = code
        w3.keccak.return_value = Mock(hex=lambda: "0xabcdef123456")
        self.assertTrue(self.manager.verify_contract_bytecode(w3, "0x1111111111111111111111111111111111111111", "0xabcdef123456"))

        # Test hash mismatch
        with self.assertRaisesRegex(ValueError, "Contract runtime code hash mismatch"):
            self.manager.verify_contract_bytecode(w3, "0x1111111111111111111111111111111111111111", "0x999999")


if __name__ == "__main__":
    unittest.main()
