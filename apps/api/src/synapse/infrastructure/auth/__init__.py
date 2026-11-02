"""Account/auth persistence for the self-hosted single-owner deployment.

Modules:

``settings``   the ``SYNAPSE_AUTH*`` environment contract
``db``         SQLAlchemy models and engine helpers (SQLite + PostgreSQL)
``passwords``  Argon2id hashing
``stores``     SQL user store, SQL/Redis session-token stores
``build``      the single composition point used by ``api.deps``
"""
