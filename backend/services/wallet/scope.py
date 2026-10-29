"""Trusted per-turn proposal context shared by API and proposal tools."""

import contextvars

proposal_scope = contextvars.ContextVar("wallet_proposal_scope", default=None)
