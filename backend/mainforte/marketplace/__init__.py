"""Marketplace v1 (IDEA.md:103): a global, per-user marketplace for goods and small gigs/services
(piano lessons, etc). Conceptual demo scope, not production-hardened -- see PLAN.md and
/Users/pmaszy/.claude/plans/temporal-weaving-cookie.md for the design writeup.

Escrow is stubbed only (marketplace/stripe_connect_stub.py never touches the network); cash is a
tracked status with no payment processing. Search is Postgres full-text plus one optional AI call
that parses a natural-language query into structured filters (marketplace/search.py) -- no
embeddings, matching the rest of this codebase's search infra.
"""
from __future__ import annotations
