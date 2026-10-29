"""Shared access checks for API route groups."""

from fastapi import HTTPException, Request


def legacy_only(request: Request) -> None:
    if request.app.state.history_enabled:
        raise HTTPException(
            status_code=403,
            detail="Legacy demo endpoints are disabled in wallet-history mode",
        )
