"""URL extractor — main content via trafilatura, respects robots.txt."""
from __future__ import annotations
from pipelines.ingestion.extractors.pdf_extractor import ExtractedPage


async def extract_url(url: str) -> list[ExtractedPage]:
    try:
        import httpx
        import trafilatura
        from urllib.robotparser import RobotFileParser
        from urllib.parse import urlparse

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        # robots.txt check
        try:
            rp = RobotFileParser()
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(robots_url)
                rp.parse(resp.text.splitlines())
            if not rp.can_fetch("*", url):
                return [ExtractedPage(1, f"[Blocked by robots.txt: {url}]", "text", {"url": url})]
        except Exception:
            pass  # If robots.txt unavailable, proceed

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "NeuroFlow/1.0"})
            response.raise_for_status()
            html = response.text

        content = trafilatura.extract(
            html, include_tables=True, include_links=False, no_fallback=False
        ) or ""

        # Metadata extraction
        meta = trafilatura.extract_metadata(html)
        metadata = {
            "url": url,
            "title": meta.title if meta else "",
            "author": meta.author if meta else "",
        }

        return [ExtractedPage(
            page_number=1,
            content=content,
            content_type="text",
            metadata=metadata,
        )]
    except Exception as e:
        return [ExtractedPage(1, f"[URL extraction error: {e}]", "text", {"url": url})]
