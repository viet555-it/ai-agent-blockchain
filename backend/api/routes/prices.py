"""Price tracking API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.price_service import PriceService

logger = logging.getLogger("backend.api.prices")

router = APIRouter(prefix="/api/prices", tags=["prices"])


class AddAlertRequest(BaseModel):
    direction: Literal["above", "below"]
    threshold: float = Field(..., gt=0, description="Target price threshold in USD")


def _get_price_service(request: Request) -> PriceService:
    """Retrieve or lazily initialize the singleton PriceService on app.state."""
    if not hasattr(request.app.state, "price_service") or request.app.state.price_service is None:
        rpc_url = None
        if hasattr(request.app.state, "network_manager"):
            try:
                config = request.app.state.network_manager.get_network_config(11155111)
                all_rpcs = config.all_rpc_urls()
                if all_rpcs:
                    rpc_url = all_rpcs[0]
            except Exception:
                pass
        request.app.state.price_service = PriceService(rpc_url=rpc_url)
    return request.app.state.price_service


@router.get("/current")
async def get_current_price(request: Request) -> dict[str, Any]:
    """Get current ETH/USD price with source, updated timestamp, and check alerts."""
    service = _get_price_service(request)
    data = await service.get_current_price()
    triggered: list[dict[str, Any]] = []
    if data.get("price_usd") is not None:
        try:
            triggered = service.check_alerts(float(data["price_usd"]))
        except Exception as e:
            logger.warning("Failed checking price alerts: %s", e)
    data["alerts_triggered"] = triggered
    return data


@router.get("/history")
async def get_price_history(request: Request, timeframe: str = "24h") -> dict[str, Any]:
    """Get historical prices for 3 timeframes: 1h, 24h, 7d."""
    service = _get_price_service(request)
    data = await service.get_price_history(timeframe=timeframe)
    if data.get("error") and "Invalid timeframe" in data["error"]:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


@router.get("/comparison")
async def get_price_comparison(request: Request) -> dict[str, Any]:
    """Get ETH comparison rates against USD, EUR, JPY, BTC."""
    service = _get_price_service(request)
    return await service.get_comparison()


@router.get("/chainlink")
async def get_chainlink_price(request: Request) -> dict[str, Any]:
    """Read latest ETH/USD price directly from Chainlink Sepolia Aggregator."""
    service = _get_price_service(request)
    data = await service.get_chainlink_price()
    if data is None:
        raise HTTPException(
            status_code=503,
            detail="Chainlink Sepolia ETH/USD oracle is currently unavailable.",
        )
    return data


@router.get("/alerts")
def get_alerts(request: Request) -> list[dict[str, Any]]:
    """List all registered price alerts."""
    service = _get_price_service(request)
    return service.get_alerts()


@router.post("/alerts")
def add_alert(request: Request, payload: AddAlertRequest) -> dict[str, Any]:
    """Register a new price alert."""
    service = _get_price_service(request)
    try:
        return service.add_alert(direction=payload.direction, threshold=payload.threshold)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/alerts/{alert_id}")
def remove_alert(request: Request, alert_id: str) -> dict[str, Any]:
    """Remove a price alert by ID."""
    service = _get_price_service(request)
    removed = service.remove_alert(alert_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "success", "removed_id": alert_id}

