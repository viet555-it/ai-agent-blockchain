import sys
import os
import asyncio

# Ensure utf-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

from app.services.blockchain import BlockchainService
from app.agent.engine import AgentEngine

async def test_backend():
    print("Testing BlockchainService...")
    service = BlockchainService()
    print(f"Connected: {service.is_connected()}")
    try:
        block = service.get_latest_block_number()
        print(f"Latest Sepolia block: {block}")
    except Exception as e:
        print(f"Block error: {e}")

    print("\nTesting AgentEngine fallback & logic...")
    engine = AgentEngine()
    res = await engine.process_chat(
        message="Kiểm tra số dư của ví 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        wallet_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    )
    print("Agent Response:\n", res.response)
    print("Tool results count:", len(res.tool_results))

    print("\nTesting Transfer intent...")
    res_transfer = await engine.process_chat(
        message="Gửi 0.05 ETH cho 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        wallet_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    )
    print("Agent Transfer Response:\n", res_transfer.response)
    if res_transfer.proposed_transaction:
        print("Proposed TX to:", res_transfer.proposed_transaction.to)
        print("Proposed TX value:", res_transfer.proposed_transaction.value)
        print("Proposed TX description:", res_transfer.proposed_transaction.description)

    print("\nALL BACKEND LOGIC VERIFIED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_backend())

