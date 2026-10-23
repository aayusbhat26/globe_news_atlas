import logging
from typing import Optional
try:
    import trafilatura
except ImportError:
    trafilatura = None

logger = logging.getLogger("pipeline.transforms.text_extractor")


class TextExtractor:
    """
    Extracts readable article content from HTML using trafilatura.
    Enforces Scraping & Paywall policy: skips extraction for paywalled articles.
    """
    def extract_from_url(self, url: str, is_paywalled: bool = False) -> Optional[str]:
        if not trafilatura or is_paywalled:
            logger.info(f"Skipping full-text extraction for paywalled domain: {url}")
            return None

        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                result = trafilatura.extract(downloaded, include_comments=False)
                return result
        except Exception as e:
            logger.warning(f"Trafilatura extraction failed for {url}: {e}")

        return None
