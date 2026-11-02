"""Per-user model credential storage (BYOK).

Modules:

``settings``  the ``SYNAPSE_CREDENTIAL_KEY`` environment contract
``crypto``    Fernet encryption/derivation for the stored keys
``db``        the ``user_model_credentials`` table
``store``     SQL adapter for that table
``guard``     SSRF check for a user-supplied base URL
``probe``     the "test connection" provider call
"""

from __future__ import annotations
