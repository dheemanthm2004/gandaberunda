"""Product name matching and extraction for Gandaberunda variants."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Regex matching Gandaberunda in various forms:
# Full forms:
#   gandaberunda, gandabherunda, ganda-berunda, ganda berunda, ganda-bherunda
# Truncated listing forms (from hmtwatches.in compact cards):
#   "HMT Women's Gandab..", "HMT Men's Gandaber..", "HMT  Men's Gandabe.."
_GANDABERUNDA_PATTERN = re.compile(
    r"\bganda[\s\-_]?(?:bh?erunda|bh?eru?n?d?a?\.\.|bh?e?\.\.|bheru?|beru?|berund|bherund|b\.\.)\b|\bganda[\s\-_]?bh?erunda",
    re.IGNORECASE,
)

# Simpler robust pattern that catches all forms starting with ganda followed by b/bh:
_PREFIX_PATTERN = re.compile(
    r"\bganda[\s\-_]?bh?(?:erunda|erund|eru|er|e|\.\.)?",
    re.IGNORECASE,
)

# Common model reference pattern for HMT watches (e.g. JLGG 01, JLGL 01, JLSS 01, JGSS 02, etc.)
_MODEL_REF_PATTERN = re.compile(
    r"\b([A-Z]{3,4}\s*[-–—]?\s*\d{2})\b",
    re.IGNORECASE,
)


def is_gandaberunda(text: str) -> bool:
    """Return True if text contains any Gandaberunda name variation or truncated form."""
    if not text:
        return False
    cleaned = text.strip()
    return bool(_GANDABERUNDA_PATTERN.search(cleaned) or _PREFIX_PATTERN.search(cleaned))


def clean_product_name(text: str) -> str:
    """Clean whitespace and HTML entities from a product name."""
    if not text:
        return ""
    import html
    cleaned = html.unescape(text)
    # Collapse multiple whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_model_ref(text: str) -> Optional[str]:
    """Attempt to extract a model reference code from watch name (e.g. 'JLGG 01', 'JLGL 01')."""
    if not text:
        return None
    m = _MODEL_REF_PATTERN.search(text)
    if m:
        # Normalize spaces: "JLGG - 01" -> "JLGG 01"
        ref = re.sub(r"\s*[-–—]\s*", " ", m.group(1)).strip()
        return ref.upper()
    return None


def normalize_url(url: str) -> str:
    """Normalize product URL by removing query params where appropriate and standardizing scheme/host."""
    if not url:
        return ""
    url = url.strip()
    parsed = urlparse(url)
    scheme = "https"
    netloc = parsed.netloc.lower()

    # Normalize hmtwatches.store to canonical www.hmtwatches.store
    if netloc in ("hmtwatches.store", "www.hmtwatches.store"):
        netloc = "www.hmtwatches.store"

    # Normalize hmtwatches.in to www.hmtwatches.in
    if netloc in ("hmtwatches.in", "www.hmtwatches.in"):
        netloc = "www.hmtwatches.in"

    path = parsed.path.rstrip("/")
    # For hmtwatches.store product pages (/product/UUID), strip query params
    if "hmtwatches.store" in netloc and "/product/" in path:
        return urlunparse((scheme, netloc, path, "", "", ""))

    # For hmtwatches.in product overview, keep the ?id=... parameter because that identifies the product
    if "hmtwatches.in" in netloc and "product_overview" in path:
        return urlunparse((scheme, netloc, path, "", parsed.query.rstrip("/"), ""))

    return urlunparse((scheme, netloc, path, "", parsed.query.rstrip("/"), ""))
