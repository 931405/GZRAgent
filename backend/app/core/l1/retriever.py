"""
Literature Retriever — Qdrant-based semantic search for academic papers.

Provides filtered vector search with academic metadata constraints
(author, year, journal, etc.).

Ref: tech_stack.md Section 4.3, design.md Section 8.2
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RetrievalResult(BaseModel):
    """A single retrieval result from the vector database."""
    doc_id: str
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    doi: str = ""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int = 0
    journal: str = ""


class LiteratureRetriever:
    """Semantic search over academic literature using Qdrant.

    Features:
    - Dense vector similarity search
    - Payload filtering (author, year, journal, etc.)
    - Configurable top-k and score threshold
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "academic_papers",
    ) -> None:
        self._host = host
        self._port = port
        self._collection_name = collection_name
        self._client = None  # Lazy init

    def _get_client(self) -> Any:
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(
                host=self._host,
                port=self._port,
            )
        return self._client

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        score_threshold: float = 0.5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[RetrievalResult]:
        """Perform semantic search with optional payload filters.

        Args:
            query_vector: Dense embedding vector for the query.
            top_k: Maximum number of results.
            score_threshold: Minimum similarity score.
            filters: Qdrant payload filter conditions, e.g.:
                {"year": {"gte": 2020}, "journal": {"value": "Nature"}}

        Returns:
            List of RetrievalResult sorted by relevance.
        """
        client = self._get_client()

        # Build Qdrant filter
        qdrant_filter = None
        if filters:
            qdrant_filter = self._build_filter(filters)

        from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

        results = client.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=qdrant_filter,
        )

        return [
            RetrievalResult(
                doc_id=str(hit.id),
                content=hit.payload.get("content", "") if hit.payload else "",
                score=hit.score,
                metadata=hit.payload or {},
                doi=hit.payload.get("doi", "") if hit.payload else "",
                title=hit.payload.get("title", "") if hit.payload else "",
                authors=hit.payload.get("authors", []) if hit.payload else [],
                year=hit.payload.get("year", 0) if hit.payload else 0,
                journal=hit.payload.get("journal", "") if hit.payload else "",
            )
            for hit in results
        ]

    def _build_filter(self, filters: dict[str, Any]) -> Any:
        """Convert simple filter dict to Qdrant Filter object."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

        conditions = []
        for field, value in filters.items():
            if isinstance(value, dict):
                # Range filter
                conditions.append(FieldCondition(
                    key=field,
                    range=Range(**value),
                ))
            else:
                # Exact match
                conditions.append(FieldCondition(
                    key=field,
                    match=MatchValue(value=value),
                ))

        return Filter(must=conditions) if conditions else None

    async def ensure_collection(
        self,
        vector_size: int = 1536,
    ) -> None:
        """Create the collection if it doesn't exist."""
        client = self._get_client()
        from qdrant_client.models import Distance, VectorParams

        collections = client.get_collections().collections
        names = [c.name for c in collections]

        if self._collection_name not in names:
            client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "Created Qdrant collection: %s (dim=%d)",
                self._collection_name, vector_size,
            )

    async def add_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> int:
        """Add documents to the collection.

        Each document dict should have:
          - id (str/int)
          - vector (list[float])
          - payload (dict with content, doi, title, authors, year, etc.)
        """
        client = self._get_client()
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=doc.get("id", i),
                vector=doc["vector"],
                payload=doc.get("payload", {}),
            )
            for i, doc in enumerate(documents)
        ]

        client.upsert(
            collection_name=self._collection_name,
            points=points,
        )
        return len(points)
