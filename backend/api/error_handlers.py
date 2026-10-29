"""HTTP error translation and cache policy for authenticated wallet APIs."""

import logging
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.services.transaction_coordinator import TransactionError
from backend.wallet_errors import WalletError, WalletErrorKind

logger = logging.getLogger("backend.api")

WALLET_ERROR_STATUS = {
    WalletErrorKind.INVALID_INPUT: 400,
    WalletErrorKind.AUTHENTICATION_REQUIRED: 401,
    WalletErrorKind.PERMISSION_DENIED: 403,
    WalletErrorKind.NOT_FOUND: 404,
    WalletErrorKind.CONFLICT: 409,
    WalletErrorKind.RATE_LIMITED: 429,
    WalletErrorKind.DEPENDENCY_UNAVAILABLE: 503,
}


def install_wallet_handlers(app: FastAPI) -> None:
    @app.exception_handler(WalletError)
    async def wallet_failure(request, error: WalletError):
        return JSONResponse(
            status_code=WALLET_ERROR_STATUS[error.kind],
            content={"detail": {"code": error.code, "message": error.message}},
        )

    @app.middleware("http")
    async def private_wallet_responses(request, call_next):
        request_id = uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as error:
            logger.warning("Wallet API request %s failed (%s)", request_id, type(error).__name__)
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": {
                        "code": "DEPENDENCY_UNAVAILABLE",
                        "message": "A required service is unavailable. Check the existing request before retrying.",
                        "request_id": request_id,
                    }
                },
            )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Request-ID"] = request_id
        elif request.url.path in {"/", "/index.html"} or request.url.path.endswith(
            (".js", ".css", ".json")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def storage_unavailable(request, error):
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "STORAGE_UNAVAILABLE",
                    "message": "Storage is unavailable. Check the existing request before retrying.",
                }
            },
        )

    @app.exception_handler(TransactionError)
    async def transaction_unavailable(request, error):
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": {"code": "TRANSACTION", "message": str(error)}},
        )
