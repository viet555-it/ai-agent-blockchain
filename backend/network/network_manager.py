"""Network Manager for multi-chain connectivity, RPC failover, and health monitoring."""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from web3 import Web3
from web3.exceptions import Web3Exception

from backend.network.config import DEFAULT_NETWORKS, ChainConfig

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
BACKEND_ABI_DIR = BASE_DIR / "abi"
CONTRACTS_EXPORTED_DIR = BASE_DIR.parent / "contracts" / "exported"


class NetworkHealth:
    def __init__(
        self,
        chain_id: int,
        rpc_url: str,
        is_healthy: bool,
        latency_ms: float,
        block_number: Optional[int] = None,
        gas_price_wei: Optional[int] = None,
        error: Optional[str] = None,
    ):
        self.chain_id = chain_id
        self.rpc_url = rpc_url
        self.is_healthy = is_healthy
        self.latency_ms = latency_ms
        self.block_number = block_number
        self.gas_price_wei = gas_price_wei
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "rpc_url": self.rpc_url,
            "status": "HEALTHY" if self.is_healthy else "UNREACHABLE",
            "latency_ms": round(self.latency_ms, 2),
            "block_number": self.block_number,
            "gas_price_wei": self.gas_price_wei,
            "error": self.error,
        }


class NetworkManager:
    """Manages blockchain network configurations, RPC connections, and health checks."""

    def __init__(self, networks: Optional[Dict[int, ChainConfig]] = None):
        self._networks: Dict[int, ChainConfig] = networks or dict(DEFAULT_NETWORKS)
        self._active_chain_id: int = 31337

    @property
    def active_chain_id(self) -> int:
        return self._active_chain_id

    def set_active_chain_id(self, chain_id: int) -> None:
        if chain_id not in self._networks:
            raise ValueError(f"Unknown network chain_id: {chain_id}. Register it first.")
        self._active_chain_id = chain_id

    def register_network(self, config: ChainConfig) -> None:
        self._networks[config.chain_id] = config

    def get_network_config(self, chain_id: Optional[int] = None) -> ChainConfig:
        target_id = chain_id if chain_id is not None else self._active_chain_id
        if target_id not in self._networks:
            raise KeyError(f"No network configuration for chain_id {target_id}")
        return self._networks[target_id]

    def list_networks(self) -> List[Dict[str, Any]]:
        return [
            {
                "chain_id": c.chain_id,
                "name": c.name,
                "native_currency": c.native_currency.symbol,
                "is_testnet": c.is_testnet,
                "rpc_count": len(c.all_rpc_urls()),
                "is_active": c.chain_id == self._active_chain_id,
            }
            for c in self._networks.values()
        ]

    def check_rpc_health(self, rpc_url: str, expected_chain_id: int, timeout: float = 4.0) -> NetworkHealth:
        """Ping an RPC URL, measure latency and verify chain ID."""
        start = time.perf_counter()
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
            if not w3.is_connected():
                return NetworkHealth(
                    chain_id=expected_chain_id,
                    rpc_url=rpc_url,
                    is_healthy=False,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error="Failed to connect to RPC endpoint",
                )
            actual_chain_id = w3.eth.chain_id
            if actual_chain_id != expected_chain_id:
                return NetworkHealth(
                    chain_id=expected_chain_id,
                    rpc_url=rpc_url,
                    is_healthy=False,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error=f"Chain ID mismatch: expected {expected_chain_id}, got {actual_chain_id}",
                )
            block_number = w3.eth.block_number
            gas_price = w3.eth.gas_price
            latency = (time.perf_counter() - start) * 1000
            return NetworkHealth(
                chain_id=expected_chain_id,
                rpc_url=rpc_url,
                is_healthy=True,
                latency_ms=latency,
                block_number=block_number,
                gas_price_wei=gas_price,
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return NetworkHealth(
                chain_id=expected_chain_id,
                rpc_url=rpc_url,
                is_healthy=False,
                latency_ms=latency,
                error=str(exc),
            )

    def get_healthy_provider(self, chain_id: Optional[int] = None) -> Tuple[Web3, str]:
        """Iterate through network's primary and fallback RPCs until a healthy provider is found."""
        config = self.get_network_config(chain_id)
        candidates = config.all_rpc_urls()
        if not candidates:
            raise ConnectionError(f"No RPC endpoints configured for network {config.name} (Chain {config.chain_id})")

        errors = []
        for url in candidates:
            health = self.check_rpc_health(url, config.chain_id)
            if health.is_healthy:
                logger.info("Connected to chain %d via healthy RPC: %s (latency: %.1fms)", config.chain_id, url, health.latency_ms)
                w3 = Web3(Web3.HTTPProvider(url))
                return w3, url
            errors.append(f"{url} -> {health.error}")

        raise ConnectionError(
            f"All RPC endpoints failed for chain {config.chain_id} ({config.name}): " + "; ".join(errors)
        )

    def load_deployment_manifest(self, chain_id: int, contract_name: str = "AgentToken") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Load ABI and deployment manifest for given chain_id."""
        folder_name = str(int(chain_id))
        search_dirs = [
            BACKEND_ABI_DIR / folder_name,
            CONTRACTS_EXPORTED_DIR / folder_name,
        ]

        abi_path = None
        manifest_path = None
        for d in search_dirs:
            p_abi = d / f"{contract_name}_abi.json"
            p_manifest = d / "deployment.json"
            if p_abi.exists() and p_manifest.exists():
                abi_path = p_abi
                manifest_path = p_manifest
                break

        if not abi_path or not manifest_path:
            raise FileNotFoundError(
                f"No {contract_name} deployment found for chain {chain_id}. "
                f"Searched in: {[str(d) for d in search_dirs]}"
            )

        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)

        if str(manifest.get("chainId")) != str(chain_id):
            raise ValueError(
                f"Deployment manifest chainId '{manifest.get('chainId')}' does not match requested chain {chain_id}"
            )

        with abi_path.open("r", encoding="utf-8") as f:
            abi = json.load(f)

        return abi, manifest

    def verify_contract_bytecode(self, w3: Web3, address: str, expected_runtime_hash: Optional[str] = None) -> bool:
        """Verify on-chain contract code exists and optionally matches the expected runtime hash."""
        checksum_addr = w3.to_checksum_address(address)
        code = w3.eth.get_code(checksum_addr)
        if not code or code == b"" or code == b"\x00":
            raise ValueError(f"No contract bytecode found at address {checksum_addr}")

        if expected_runtime_hash:
            actual_hash = w3.keccak(code).hex().lower().removeprefix("0x")
            clean_expected = expected_runtime_hash.lower().removeprefix("0x")
            if actual_hash != clean_expected:
                raise ValueError(
                    f"Contract runtime code hash mismatch at {checksum_addr}: "
                    f"expected {clean_expected}, got {actual_hash}"
                )
        return True
