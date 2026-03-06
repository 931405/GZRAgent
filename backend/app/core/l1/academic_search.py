"""
External Academic Search API Clients.

Provides async clients for real academic paper retrieval:
  - Semantic Scholar (primary): free API, titles/abstracts/DOI/citations
  - arXiv (supplementary): preprints, full text
  - CrossRef (supplementary): DOI validation, metadata

All clients return a unified PaperResult model.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified result model
# ---------------------------------------------------------------------------

class PaperResult(BaseModel):
    """Unified paper result from any academic search source."""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int = 0
    abstract: str = ""
    doi: str = ""
    url: str = ""
    venue: str = ""
    citation_count: int = 0
    source: str = ""  # semantic_scholar / arxiv / crossref / qdrant
    relevance_score: float = 0.0

    @property
    def authors_short(self) -> str:
        """Format authors for citation, e.g. 'Zhang et al., 2023'."""
        if not self.authors:
            return "Unknown"
        first = self.authors[0].split()[-1]  # Last name
        if len(self.authors) > 2:
            return f"{first} et al."
        elif len(self.authors) == 2:
            second = self.authors[1].split()[-1]
            return f"{first} & {second}"
        return first

    @property
    def citation_key(self) -> str:
        """Generate a citation key like [Zhang et al., 2023]."""
        return f"[{self.authors_short}, {self.year}]" if self.year else f"[{self.authors_short}]"

    def to_evidence_block(self, index: int) -> str:
        """Format as a readable evidence block for LLM consumption."""
        lines = [f"[文献{index}] {self.title}"]
        lines.append(f"  作者：{', '.join(self.authors[:3])}{'等' if len(self.authors) > 3 else ''}")
        if self.year:
            lines.append(f"  年份：{self.year}")
        if self.venue:
            lines.append(f"  来源：{self.venue}")
        if self.doi:
            lines.append(f"  DOI：{self.doi}")
        if self.citation_count:
            lines.append(f"  引用数：{self.citation_count}")
        if self.abstract:
            lines.append(f"  摘要：{self.abstract[:300]}...")
        lines.append(f"  建议引用格式：{self.citation_key}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Semantic Scholar Client
# ---------------------------------------------------------------------------

class SemanticScholarClient:
    """Search papers via Semantic Scholar Graph API (free, no key required)."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    FIELDS = "title,abstract,authors,year,citationCount,externalIds,url,venue"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def search(self, query: str, limit: int = 5) -> list[PaperResult]:
        """Search for papers by keyword query."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/paper/search",
                params={
                    "query": query,
                    "limit": limit,
                    "fields": self.FIELDS,
                },
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for paper in data.get("data", []):
            if not paper:
                continue
            authors = [a.get("name", "") for a in (paper.get("authors") or [])]
            doi = ""
            ext_ids = paper.get("externalIds") or {}
            if ext_ids:
                doi = ext_ids.get("DOI", "")

            results.append(PaperResult(
                title=paper.get("title") or "",
                authors=authors,
                year=paper.get("year") or 0,
                abstract=(paper.get("abstract") or "")[:500],
                doi=doi,
                url=paper.get("url") or "",
                venue=paper.get("venue") or "",
                citation_count=paper.get("citationCount") or 0,
                source="semantic_scholar",
            ))
        return results


# ---------------------------------------------------------------------------
# arXiv Client
# ---------------------------------------------------------------------------

class ArxivClient:
    """Search preprints via arXiv API (free, no key required)."""

    BASE_URL = "http://export.arxiv.org/api/query"
    NS = {"atom": "http://www.w3.org/2005/Atom"}

    async def search(self, query: str, limit: int = 5) -> list[PaperResult]:
        """Search arXiv by keyword query."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                self.BASE_URL,
                params={
                    "search_query": f"all:{query}",
                    "max_results": limit,
                    "sortBy": "relevance",
                },
            )
            resp.raise_for_status()

        return self._parse_atom_feed(resp.text)

    def _parse_atom_feed(self, xml_text: str) -> list[PaperResult]:
        """Parse arXiv Atom XML response into PaperResult list."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("Failed to parse arXiv XML response")
            return []

        results = []
        for entry in root.findall("atom:entry", self.NS):
            title = (entry.findtext("atom:title", "", self.NS) or "").strip()
            title = re.sub(r"\s+", " ", title)  # Collapse whitespace
            abstract = (entry.findtext("atom:summary", "", self.NS) or "").strip()[:500]

            authors = []
            for author_el in entry.findall("atom:author", self.NS):
                name = author_el.findtext("atom:name", "", self.NS)
                if name:
                    authors.append(name)

            published = entry.findtext("atom:published", "", self.NS) or ""
            year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else 0

            url = ""
            doi = ""
            for link in entry.findall("atom:link", self.NS):
                href = link.get("href", "")
                if link.get("title") == "doi":
                    doi = href.replace("http://dx.doi.org/", "").replace("https://doi.org/", "")
                elif link.get("type") == "text/html" or (not url and href):
                    url = href

            if not url:
                url = entry.findtext("atom:id", "", self.NS) or ""

            if title:
                results.append(PaperResult(
                    title=title,
                    authors=authors,
                    year=year,
                    abstract=abstract,
                    doi=doi,
                    url=url,
                    venue="arXiv",
                    source="arxiv",
                ))
        return results


# ---------------------------------------------------------------------------
# CrossRef Client
# ---------------------------------------------------------------------------

class CrossRefClient:
    """Search papers via CrossRef API (free, polite pool with email)."""

    BASE_URL = "https://api.crossref.org/works"

    async def search(self, query: str, limit: int = 5) -> list[PaperResult]:
        """Search CrossRef for published works by keyword query."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                self.BASE_URL,
                params={
                    "query": query,
                    "rows": limit,
                    "select": "DOI,title,author,published-print,container-title,"
                              "is-referenced-by-count,abstract",
                },
                headers={
                    "User-Agent": "PD-MAWS/0.1 (mailto:pdmaws-research@example.com)",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("message", {}).get("items", []):
            title_list = item.get("title", [])
            title = title_list[0] if title_list else ""

            authors = []
            for author in item.get("author", []):
                name = f"{author.get('given', '')} {author.get('family', '')}".strip()
                if name:
                    authors.append(name)

            year = 0
            date_parts = item.get("published-print", {}).get("date-parts", [[]])
            if date_parts and date_parts[0]:
                year = date_parts[0][0] if date_parts[0][0] else 0

            venue_list = item.get("container-title", [])
            venue = venue_list[0] if venue_list else ""

            abstract = item.get("abstract") or ""
            abstract = re.sub(r"<[^>]+>", "", abstract)[:500]

            doi = item.get("DOI", "")
            results.append(PaperResult(
                title=title,
                authors=authors,
                year=year,
                abstract=abstract,
                doi=doi,
                url=f"https://doi.org/{doi}" if doi else "",
                venue=venue,
                citation_count=item.get("is-referenced-by-count", 0),
                source="crossref",
            ))
        return results
