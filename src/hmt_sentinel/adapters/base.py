"""Base adapter interface and shared HTTP utilities."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests

from hmt_sentinel.models import Product

logger = logging.getLogger(__name__)

ALLOWED_DOMAINS = {
    "hmtwatches.store",
    "www.hmtwatches.store",
    "hmtwatches.in",
    "www.hmtwatches.in",
}

_SESSION: Optional[requests.Session] = None
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB maximum per response


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
    return _SESSION


def normalize_request_url(url: str) -> str:
    """Normalize apex hmtwatches.store to canonical www.hmtwatches.store to ensure reliable TLS."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc == "hmtwatches.store":
        netloc = "www.hmtwatches.store"
    elif netloc == "hmtwatches.in":
        netloc = "www.hmtwatches.in"
    return urlunparse((parsed.scheme or "https", netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def fetch(
    url: str,
    *,
    timeout: int = 20,
    retries: int = 3,
    method: str = "GET",
    data: Optional[dict] = None,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Optional[requests.Response]:
    """Fetch a URL with retries, exponential backoff, and domain security checks.
    
    Returns None if request fails or domain is disallowed.
    """
    normalized_url = normalize_request_url(url)
    parsed = urlparse(normalized_url)
    if parsed.netloc.lower() not in ALLOWED_DOMAINS:
        logger.error("Blocked request to disallowed domain: %s (url: %s)", parsed.netloc, url)
        return None

    session = _get_session()
    req_headers = dict(headers or {})

    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "POST":
                resp = session.post(
                    normalized_url,
                    data=data,
                    headers=req_headers,
                    params=params,
                    timeout=timeout,
                    stream=True,
                )
            else:
                resp = session.get(
                    normalized_url,
                    headers=req_headers,
                    params=params,
                    timeout=timeout,
                    stream=True,
                )

            resp.raise_for_status()

            # Bounded content consumption
            content = resp.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
            if len(content) > MAX_RESPONSE_BYTES:
                logger.warning("Response from %s exceeded size limit (%d bytes)", normalized_url, MAX_RESPONSE_BYTES)
                return None

            # Attach bounded content back to response
            resp._content = content
            return resp

        except requests.RequestException as exc:
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt,
                retries,
                normalized_url,
                exc,
            )
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    return None


class BaseAdapter(ABC):
    domain: str
    last_error: Optional[str] = None

    @abstractmethod
    def discover(self) -> list[Product]:
        """Discover all Gandaberunda products. Returns list of Product instances."""

    @abstractmethod
    def check_product(self, product: Product) -> Product:
        """Re-check availability of a single product. Returns updated Product."""
