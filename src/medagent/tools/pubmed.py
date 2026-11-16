"""PubMed / PubMed Central access through the NCBI E-utilities API.

The module separates network calls from XML parsing so the parsers can be
tested with fixtures and the network layer can be swapped.
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..config import Config
from ..types import Evidence
from .base import Tool, ToolResult, ToolUnavailable

logger = logging.getLogger(__name__)

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

PMC_ARTICLE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
# Legacy direct-image path; PMC now serves figures from CDN blob URLs that are
# resolved from the article page HTML (see resolve_figure_urls).
PMC_FIGURE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/bin/{href}"
PMC_BLOB_RE = r"https://cdn\.ncbi\.nlm\.nih\.gov/pmc/blobs/[^\"\']+"


class RateLimiter:
    """Simple spacing-based limiter for the NCBI 3 req/s default."""

    def __init__(self, per_second: float) -> None:
        self.min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


class NcbiClient:
    """Thin async client for esearch/efetch with retries."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg.pubmed
        self.limiter = RateLimiter(cfg.pubmed.rate_limit_per_sec)
        self.timeout = 40.0
        self.max_retries = 3

    def _common_params(self) -> dict[str, str]:
        params = {"tool": self.cfg.tool, "email": self.cfg.email}
        if self.cfg.api_key:
            params["api_key"] = self.cfg.api_key
        return params

    async def _get(self, url: str, params: dict[str, Any]) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            await self.limiter.wait()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params={**self._common_params(), **params})
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.text
            except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 8))
        raise ToolUnavailable(f"NCBI request failed: {last_error}")

    async def esearch(self, term: str, retmax: int) -> list[str]:
        xml = await self._get(
            ESEARCH,
            {
                "db": "pubmed",
                "term": term,
                "retmax": retmax,
                "retmode": "xml",
                "sort": "relevance",
            },
        )
        root = ET.fromstring(xml)
        return [node.text.strip() for node in root.findall(".//IdList/Id") if node.text]

    async def efetch_pubmed(self, pmids: list[str]) -> list[dict[str, Any]]:
        if not pmids:
            return []
        xml = await self._get(
            EFETCH,
            {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"},
        )
        return parse_pubmed_records(xml)

    async def efetch_pmc(self, pmcid: str) -> dict[str, Any] | None:
        try:
            xml = await self._get(EFETCH, {"db": "pmc", "id": pmcid, "retmode": "xml"})
        except ToolUnavailable:
            return None
        try:
            article = parse_pmc_article(xml, pmcid)
        except ET.ParseError:
            return None
        await self.resolve_figure_urls(article)
        return article

    async def resolve_figure_urls(self, article: dict[str, Any]) -> None:
        """Resolve CDN image URLs for the article figures from its HTML page."""
        figures = article.get("figures") or []
        if not figures:
            return
        page_id = article.get("page_id") or ""
        if not page_id:
            return
        import re

        try:
            html = await self._get(PMC_ARTICLE_URL.format(pmcid=page_id), {})
        except ToolUnavailable:
            return
        blob_urls = re.findall(PMC_BLOB_RE, html)
        for figure in figures:
            href = figure.get("href", "")
            if not href:
                continue
            for url in blob_urls:
                if url.endswith("/" + href) or url.endswith(href):
                    figure["image_url"] = url
                    break
            if "image_url" not in figure:
                figure["image_url"] = PMC_FIGURE_URL.format(pmcid=page_id, href=href)


def _clean(text: str | None) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def parse_pubmed_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse an efetch db=pubmed XML payload into records."""
    root = ET.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _clean(article.findtext(".//MedlineCitation/PMID"))
        title = _clean(article.findtext(".//Article/ArticleTitle"))
        journal = _clean(article.findtext(".//Journal/Title"))
        year = _clean(article.findtext(".//JournalIssue/PubDate/Year")) or _clean(
            article.findtext(".//JournalIssue/PubDate/MedlineDate")
        )
        abstract = " ".join(
            _clean(node.text) for node in article.findall(".//Article/Abstract/AbstractText")
        )
        pmcid = ""
        for article_id in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if article_id.get("IdType") == "pmc" and article_id.text:
                pmcid = article_id.text.strip()
        records.append(
            {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "year": year,
                "abstract": abstract,
                "pmcid": pmcid,
            }
        )
    return records


def parse_pmc_article(xml_text: str, pmcid: str) -> dict[str, Any]:
    """Parse a JATS PMC full-text payload into text plus figure metadata."""
    root = ET.fromstring(xml_text)
    title = _clean(root.findtext(".//article-title"))
    paragraphs = [_clean(node.text) for node in root.findall(".//body//p")]
    figures: list[dict[str, str]] = []
    xlink_ns = "http://www.w3.org/1999/xlink"
    for fig in root.findall(".//fig"):
        label = _clean(fig.findtext("label"))
        caption_node = fig.find("caption")
        caption = _clean(" ".join(caption_node.itertext())) if caption_node is not None else ""
        graphic = fig.find("graphic")
        href = graphic.get("{" + xlink_ns + "}href") if graphic is not None else None
        figures.append({"label": label, "caption": caption, "href": href or ""})
    page_id = pmcid.upper() if pmcid.upper().startswith("PMC") else "PMC" + pmcid
    for figure in figures:
        if figure["href"]:
            figure["image_url"] = PMC_FIGURE_URL.format(pmcid=page_id, href=figure["href"])
    return {
        "title": title,
        "page_id": page_id,
        "text": "\n".join(p for p in paragraphs if p),
        "figures": figures,
        "url": PMC_ARTICLE_URL.format(pmcid=page_id),
    }


class PubMedTool(Tool):
    """Search PubMed and fetch one paper plus its figures."""

    name = "search_pubmed"
    description = (
        "Search PubMed for biomedical evidence. Returns titles, abstracts, journal/year "
        "and PMID/PMCID identifiers. Use action=fetch with a pmid to get one paper."
    )
    args_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "fetch"]},
            "query": {"type": "string", "description": "PubMed search terms"},
            "pmid": {"type": "string", "description": "PubMed id for action=fetch"},
            "retmax": {"type": "integer", "default": 8},
        },
        "required": ["action"],
    }

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = NcbiClient(cfg)

    async def run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "search")).lower()
        if action == "fetch":
            pmid = str(args.get("pmid") or "").strip()
            pmcid = str(args.get("pmcid") or "").strip()
            return await self._fetch(pmid=pmid, pmcid=pmcid)
        return await self._search(str(args.get("query") or "").strip(), int(args.get("retmax") or 8))

    async def _search(self, query: str, retmax: int) -> ToolResult:
        if not query:
            return ToolResult(observation="search_pubmed needs a non-empty query.")
        pmids = await self.client.esearch(query, max(1, min(retmax, 15)))
        if not pmids:
            return ToolResult(observation=f"No PubMed results for: {query}")
        records = await self.client.efetch_pubmed(pmids)
        evidence: list[Evidence] = []
        lines: list[str] = []
        for idx, record in enumerate(records, start=1):
            pmid = record.get("pmid", "")
            evidence_id = f"PMID{pmid}"
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    kind="abstract",
                    source=pmid,
                    title=record.get("title", ""),
                    text=record.get("abstract", ""),
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    meta={
                        "journal": record.get("journal", ""),
                        "year": record.get("year", ""),
                        "pmcid": record.get("pmcid", ""),
                    },
                )
            )
            abstract_preview = (record.get("abstract", "") or "")[:420]
            lines.append(
                f"{idx}. [{evidence_id}] {record.get('title', '')} "
                f"({record.get('journal', '')}, {record.get('year', '')}) {abstract_preview}"
            )
        observation = "\n".join(lines)
        return ToolResult(observation=observation, evidence=evidence)

    async def _fetch(self, pmid: str, pmcid: str) -> ToolResult:
        evidence: list[Evidence] = []
        lines: list[str] = []
        if pmid:
            records = await self.client.efetch_pubmed([pmid])
            if records:
                record = records[0]
                pmcid = pmcid or record.get("pmcid", "")
                evidence.append(
                    Evidence(
                        evidence_id=f"PMID{pmid}",
                        kind="abstract",
                        source=pmid,
                        title=record.get("title", ""),
                        text=record.get("abstract", ""),
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        meta={"journal": record.get("journal", ""), "year": record.get("year", "")},
                    )
                )
                lines.append(f"Abstract [PMID{pmid}]: " + record.get("abstract", "")[:900])
        if pmcid:
            article = await self.client.efetch_pmc(pmcid)
            if article:
                evidence.append(
                    Evidence(
                        evidence_id=f"PMC{pmcid}",
                        kind="fulltext",
                        source=pmcid,
                        title=article.get("title", ""),
                        text=article.get("text", "")[:20000],
                        url=article.get("url", ""),
                        meta={"figures": len(article.get("figures", []))},
                    )
                )
                lines.append("Full text available in evidence PMC" + pmcid)
                for figure in article.get("figures", []):
                    label = figure.get("label") or "Figure"
                    image_url = figure.get("image_url", "")
                    evidence.append(
                        Evidence(
                            evidence_id=f"FIG:{pmcid}:{figure.get('href', '')}",
                            kind="figure",
                            source=pmcid,
                            title=label,
                            text=figure.get("caption", ""),
                            url=image_url,
                            meta={"pmcid": pmcid, "image_url": image_url},
                        )
                    )
                    lines.append(f"Figure {label}: {figure.get('caption', '')[:240]} image_url={image_url}")
        if not evidence:
            return ToolResult(observation=f"Could not fetch paper {pmid or pmcid}.")
        return ToolResult(observation="\n".join(lines), evidence=evidence)