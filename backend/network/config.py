"""Network configurations and chain definitions for Blockchain Service."""
import os
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class NativeCurrency(BaseModel):
    name: str = "Ether"
    symbol: str = "ETH"
    decimals: int = 18


class ChainConfig(BaseModel):
    chain_id: int
    name: str
    rpc_urls: List[str]
    fallback_rpc_urls: List[str] = Field(default_factory=list)
    native_currency: NativeCurrency = Field(default_factory=NativeCurrency)
    block_explorer_url: Optional[str] = None
    is_testnet: bool = True
    default_contracts: Dict[str, str] = Field(default_factory=dict)

    def all_rpc_urls(self) -> List[str]:
        """Return unique ordered list of all available RPC endpoints."""
        seen = set()
        result = []
        for url in self.rpc_urls + self.fallback_rpc_urls:
            cleaned = url.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


# Default built-in networks
DEFAULT_NETWORKS: Dict[int, ChainConfig] = {
    31337: ChainConfig(
        chain_id=31337,
        name="Hardhat Localhost",
        rpc_urls=[
            os.getenv("LOCAL_RPC_URL", "http://127.0.0.1:8545"),
            "http://localhost:8545",
        ],
        fallback_rpc_urls=[],
        native_currency=NativeCurrency(name="Local Ether", symbol="ETH", decimals=18),
        block_explorer_url=None,
        is_testnet=True,
    ),
    11155111: ChainConfig(
        chain_id=11155111,
        name="Ethereum Sepolia Testnet",
        rpc_urls=[
            os.getenv("SEPOLIA_RPC_URL") or "https://rpc.sepolia.org",
            "https://ethereum-sepolia.publicnode.com",
            "https://1rpc.io/sepolia",
        ],
        fallback_rpc_urls=[
            "https://rpc2.sepolia.org",
            "https://gateway.tenderly.co/public/sepolia",
        ],
        native_currency=NativeCurrency(name="Sepolia Ether", symbol="ETH", decimals=18),
        block_explorer_url="https://sepolia.etherscan.io",
        is_testnet=True,
        default_contracts={
            "AgentToken": "0xDf7B0c367817f97d756441da6047a1Da91cC6Fff",
        },
    ),
}
