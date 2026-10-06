from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import WalletInfoResponse, TransactionStatusResponse
from app.services.blockchain import BlockchainService
from app.core.config import settings

router = APIRouter(prefix="/wallet", tags=["Wallet & Blockchain"])

@router.get("/info", response_model=WalletInfoResponse)
async def get_wallet_info(
    address: str = Query(..., description="EVM wallet address (0x...)"),
    chain_id: int = Query(default=11155111, description="Chain ID")
):
    try:
        service = BlockchainService(chain_id=chain_id)
        balance_data = service.get_native_balance(address)
        latest_block = service.get_latest_block_number()
        
        return WalletInfoResponse(
            address=balance_data["address"],
            chain_id=balance_data["chain_id"],
            chain_name=settings.CHAIN_NAME,
            native_balance=balance_data["balance_eth"],
            native_symbol=balance_data["symbol"],
            explorer_url=f"{settings.EXPLORER_URL}/address/{balance_data['address']}",
            block_number=latest_block
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tx/{tx_hash}", response_model=TransactionStatusResponse)
async def get_tx_status(
    tx_hash: str,
    chain_id: int = Query(default=11155111, description="Chain ID")
):
    try:
        service = BlockchainService(chain_id=chain_id)
        data = service.get_transaction_status(tx_hash)
        return TransactionStatusResponse(
            tx_hash=data.get("tx_hash", tx_hash),
            status=data.get("status", "not_found"),
            block_number=data.get("block_number"),
            gas_used=data.get("gas_used"),
            from_address=data.get("from_address"),
            to_address=data.get("to_address"),
            value=data.get("value"),
            explorer_url=data.get("explorer_url", f"{settings.EXPLORER_URL}/tx/{tx_hash}")
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

