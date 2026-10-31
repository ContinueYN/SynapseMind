"""Local, read-only knowledge retrieval.

The corpus is a small JSONL file checked into the repository; vectors are built
in process at startup. This is deliberately not a vector database yet: the
corpus is tiny and single-user. The port in ``application/knowledge.py`` is the
seam for PostgreSQL/pgvector later.
"""

from synapse.application.knowledge import KnowledgeService
from synapse.infrastructure.knowledge.builder import build_knowledge_service

__all__ = ["KnowledgeService", "build_knowledge_service"]
