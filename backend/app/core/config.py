from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "Web3 AI Agent System"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # OpenAI Settings
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini", description="OpenAI Model name")
    
    # Web3 / EVM Blockchain Settings
    RPC_URL: str = Field(
        default="https://ethereum-sepolia-rpc.publicnode.com",
        description="EVM RPC Node URL (Sepolia Testnet)"
    )
    CHAIN_ID: int = Field(default=11155111, description="Chain ID (Sepolia: 11155111)")
    CHAIN_NAME: str = Field(default="Sepolia Testnet", description="Chain name")
    EXPLORER_URL: str = Field(default="https://sepolia.etherscan.io", description="Explorer base URL")
    
    # Guardrail / Policy Engine Settings (Section 3.1 & 4.2 in Report)
    GUARDRAIL_MAX_ETH_TRANSFER: float = Field(default=0.1, description="Maximum allowed ETH transfer per transaction without admin override")
    GUARDRAIL_MAX_TOKEN_TRANSFER: float = Field(default=500.0, description="Maximum allowed token amount per transaction")
    GUARDRAIL_REQUIRE_HUMAN_APPROVAL: bool = Field(default=True, description="Enforce human-in-the-loop signature before execution")
    GUARDRAIL_SIMULATION_ENABLED: bool = Field(default=True, description="Simulate transaction dry-run before proposing")
    
    # Default Whitelisted Addresses (for Guardrail policy)
    GUARDRAIL_WHITELIST: List[str] = [
        "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", # Vitalik demo address
        "0x71C9491133502447972423423719011234567890", # Demo team wallet
        "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238", # Sepolia USDC
        "0x779877A7B0D9E8603169DdbD7836e478b4624789", # Sepolia LINK
    ]
    
    # Blacklisted / High-Risk Addresses
    GUARDRAIL_BLACKLIST: List[str] = [
        "0x0000000000000000000000000000000000000000",
        "0xdead000000000000000000000000000000000000",
    ]
    
    # Optional Agent Private Key for server-side testing
    AGENT_PRIVATE_KEY: Optional[str] = Field(default=None, description="Optional testnet private key")
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
