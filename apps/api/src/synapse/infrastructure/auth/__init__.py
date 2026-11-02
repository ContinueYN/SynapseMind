"""Account/auth persistence for a self-hosted, multi-user deployment.

Modules:

``settings``   the ``SYNAPSE_AUTH*`` environment contract
``db``         SQLAlchemy models and engine helpers (SQLite + PostgreSQL)
``passwords``  Argon2id hashing
``stores``     SQL user store, SQL/Redis one-time session-token stores
``build``      the single composition point used by ``api.deps``
"""

from __future__ import annotations
