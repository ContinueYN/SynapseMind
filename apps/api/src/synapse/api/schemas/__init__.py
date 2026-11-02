"""HTTP DTOs, split by resource.

These are protocol shapes, not domain objects. Keeping them here prevents
FastAPI/Pydantic from leaking into the domain layer.

Modules:

``common``      shared base model
``auth``        register/login/logout/me
``sessions``    sessions, intake, diagnosis, hints, scaffolds and step checks
``review``      generic review and the internal review queue
``agent``       bounded agent trace
``execution``   explicit code execution
``knowledge``   knowledge card search
``health``      health check
``coach``       process coach
``settings``    per-user model credentials (BYOK)

Import the feature module directly (for example
``synapse.api.schemas.sessions``); there is no aggregate module.
"""
