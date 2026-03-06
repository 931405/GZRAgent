"""
Composite Evidence Service — merges Qdrant local search + external APIs.

Search priority:
  1. Qdrant local vector DB (if enabled and has data)
  2. Semantic Scholar API (primary external)
  3. arXiv API (preprints)
  4. CrossRef API (published works)

Features:
  - Parallel search across all sources
  - Deduplication by DOI / normalized title
  - Ranking by citation count + relevance score
  - Graceful degradation (any source can fail independently)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EvidenceService:
    """Unified evidence retrieval combining local Qdrant + external APIs."""

    def __init__(self) -> None:
        self._s2_client: Any = None
        self._arxiv_client: Any = None
        self._crossref_client: Any = None
        self._retriever: Any = None
        self._settings: Any = None

    def _get_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings
            self._settings = get_settings()
        return self._settings

    def _get_s2(self) -> Any:
        if self._s2_client is None:
            from app.core.l1.academic_search import SemanticScholarClient
            settings = self._get_settings()
            self._s2_client = SemanticScholarClient(
                api_key=getattr(settings, "semantic_scholar_api_key", ""),
            )
        return self._s2_client

    def _get_arxiv(self) -> Any:
        if self._arxiv_client is None:
            from app.core.l1.academic_search import ArxivClient
            self._arxiv_client = ArxivClient()
        return self._arxiv_client

    def _get_crossref(self) -> Any:
        if self._crossref_client is None:
            from app.core.l1.academic_search import CrossRefClient
            self._crossref_client = CrossRefClient()
        return self._crossref_client

    def _get_retriever(self) -> Any:
        if self._retriever is None:
            from app.core.l1.retriever import LiteratureRetriever
            settings = self._get_settings()
            self._retriever = LiteratureRetriever(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
            )
        return self._retriever

    # ------------------------------------------------------------------
    # Main search API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search across all sources, merge, deduplicate, and rank.

        Returns a list of dicts with paper metadata, ready for prompt injection.
        """
        from app.core.l1.academic_search import PaperResult

        settings = self._get_settings()
        per_source = max(limit // 2, 3)

        tasks: list[asyncio.Task] = []
        source_names: list[str] = []

        # External API searches
        if getattr(settings, "evidence_search_enabled", True):
            tasks.append(self._safe_search(self._get_s2(), query, per_source))
            source_names.append("Semantic Scholar")
            tasks.append(self._safe_search(self._get_arxiv(), query, per_source))
            source_names.append("arXiv")
            tasks.append(self._safe_search(self._get_crossref(), query, per_source))
            source_names.append("CrossRef")

        # Qdrant local search
        if getattr(settings, "evidence_qdrant_enabled", True):
            tasks.append(self._search_qdrant(query, per_source))
            source_names.append("Qdrant")

        if not tasks:
            logger.warning("No evidence sources enabled")
            return []

        results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers: list[PaperResult] = []
        for i, result in enumerate(results_per_source):
            name = source_names[i] if i < len(source_names) else "unknown"
            if isinstance(result, BaseException):
                logger.warning("Evidence search failed [%s]: %s", name, result)
                continue
            if isinstance(result, list):
                logger.info("Evidence search [%s]: found %d papers", name, len(result))
                all_papers.extend(result)

        # Deduplicate
        unique = self._deduplicate(all_papers)

        # Rank: citation_count (descending) → relevance_score (descending)
        unique.sort(
            key=lambda p: (p.citation_count, p.relevance_score),
            reverse=True,
        )

        final = unique[:limit]

        logger.info(
            "Evidence search total: %d raw → %d unique → %d returned",
            len(all_papers), len(unique), len(final),
        )

        return [self._paper_to_dict(p, idx) for idx, p in enumerate(final, 1)]

    # ------------------------------------------------------------------
    # Source-specific search
    # ------------------------------------------------------------------

    async def _safe_search(self, client: Any, query: str, limit: int) -> list:
        """Wrapper that never raises, returns [] on failure."""
        try:
            return await client.search(query, limit)
        except Exception as e:
            logger.warning("Search failed for %s: %s", type(client).__name__, e)
            return []

    async def _search_qdrant(self, query: str, limit: int) -> list:
        """Search Qdrant via embedding vector."""
        from app.core.l1.academic_search import PaperResult

        embedding = await self._get_embedding(query)
        if not embedding:
            return []

        try:
            retriever = self._get_retriever()
            hits = await retriever.search(
                query_vector=embedding,
                top_k=limit,
                score_threshold=0.4,
            )
            return [
                PaperResult(
                    title=hit.title,
                    authors=hit.authors,
                    year=hit.year,
                    abstract=hit.content[:500],
                    doi=hit.doi,
                    venue=hit.journal,
                    source="qdrant",
                    relevance_score=hit.score,
                )
                for hit in hits
            ]
        except Exception as e:
            logger.warning("Qdrant search failed: %s", e)
            return []

    async def _get_embedding(self, text: str) -> Optional[list[float]]:
        """Generate embedding using an OpenAI-compatible API.

        Tries OpenAI key first, then DeepSeek. Returns None if
        no embedding-capable provider is available.
        """
        settings = self._get_settings()
        api_key = settings.openai_api_key
        base_url = settings.openai_base_url
        model = getattr(settings, "embedding_model", "text-embedding-3-small")

        if not api_key:
            # Fallback to DeepSeek (OpenAI-compatible)
            api_key = settings.deepseek_api_key
            base_url = settings.deepseek_base_url

        if not api_key:
            logger.debug("No embedding provider available, skipping Qdrant search")
            return None

        try:
            import openai
            client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
            response = await client.embeddings.create(model=model, input=text)
            return response.data[0].embedding
        except Exception as e:
            logger.warning("Embedding generation failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Deduplication & formatting
    # ------------------------------------------------------------------

    def _deduplicate(self, papers: list) -> list:
        """Remove duplicate papers by DOI or normalized title."""
        seen_dois: set[str] = set()
        seen_titles: set[str] = set()
        unique = []

        for paper in papers:
            doi_key = paper.doi.lower().strip() if paper.doi else ""
            title_key = self._normalize_title(paper.title)

            if doi_key and doi_key in seen_dois:
                continue
            if title_key and title_key in seen_titles:
                continue

            if doi_key:
                seen_dois.add(doi_key)
            if title_key:
                seen_titles.add(title_key)
            unique.append(paper)

        return unique

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for deduplication (lowercase, strip punctuation)."""
        import re
        t = title.lower().strip()
        t = re.sub(r"[^\w\s]", "", t)
        t = re.sub(r"\s+", " ", t)
        return t

    @staticmethod
    def _paper_to_dict(paper: Any, index: int) -> dict[str, Any]:
        """Convert PaperResult to a dict for storage in evidence_map."""
        return {
            "index": index,
            "title": paper.title,
            "authors": paper.authors,
            "authors_short": paper.authors_short,
            "year": paper.year,
            "abstract": paper.abstract,
            "doi": paper.doi,
            "url": paper.url,
            "venue": paper.venue,
            "citation_count": paper.citation_count,
            "source": paper.source,
            "relevance_score": paper.relevance_score,
            "citation_key": paper.citation_key,
            "evidence_block": paper.to_evidence_block(index),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: Optional[EvidenceService] = None


def get_evidence_service() -> EvidenceService:
    """Get or create the global EvidenceService singleton."""
    global _service
    if _service is None:
        _service = EvidenceService()
    return _service
