"""One read-only RPC reconciliation pass; never signs or broadcasts."""

import asyncio

from config.environment import load_project_env


async def main():
    load_project_env()
    from backend.api.server import create_app

    app = create_app()
    if not app.state.history_enabled:
        raise RuntimeError("Enable WALLET_HISTORY_ENABLED first")
    async with app.router.lifespan_context(app):
        await asyncio.to_thread(app.state.browser_wallet.reconcile_batch)
    print("Reconciliation completed; no transaction was sent.")


if __name__ == "__main__":
    asyncio.run(main())
