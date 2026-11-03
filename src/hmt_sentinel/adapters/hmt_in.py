"""Adapter for hmtwatches.in.

Discovery strategy (verified live):
  POST https://www.hmtwatches.in/filter_products_collections
  with collection_val=64 (Gandaberunda collection ID, confirmed from site source)
  Paginates with load_more_count=1, 2, ...
  Returns JSON: {"status": true, "html": "<rendered product cards>"}

HTML Parsing:
  - Product links: href="https://www.hmtwatches.in/product_overview?id=..."
  - Product name in .bc_p_name span (may be truncated on card, e.g. "HMT Women's Gandab..")
  - Price in .bc_p_detail p (e.g. "RS. 2499")
  - Availability from card:
      <div class="outofstock"><strong>Coming Soon</strong></div> -> COMING_SOON
      <div class="outofstock"><strong>Out of Stock</strong></div> -> OUT_OF_STOCK
      Add to Cart button enabled -> IN_STOCK

Product Detail Check:
  GET https://www.hmtwatches.in/product_overview?id=<token>
  - Resolves full untruncated product name from h3.product-title
  - Extracts model ref (e.g. JLGL 01, JLGG 01)
  - Updates latest price
  - Conservative stock classification via hmt_sentinel.availability
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hmt_sentinel.adapters.base import BaseAdapter, fetch
from hmt_sentinel.availability import (
    classify_from_html,
)
from hmt_sentinel.matching import (
    clean_product_name,
    extract_model_ref,
    is_gandaberunda,
    is_kannadiga,
    is_target_watch,
    normalize_url,
)
from hmt_sentinel.models import AvailabilityState, Product, utcnow

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hmtwatches.in"
COLLECTION_API = f"{BASE_URL}/filter_products_collections"
SEARCH_API = f"{BASE_URL}/search_products"
GANDABERUNDA_COLLECTION_ID = 64

_CSRF_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{BASE_URL}/collections?type=collection&id={GANDABERUNDA_COLLECTION_ID}",
}


def _extract_product_id(item, url: str) -> str:
    """Extract a stable product ID from the card."""
    # Look for notifyMe(1216) in onclick attribute
    onclick = str(item)
    m = re.search(r"notifyMe\((\d+)\)", onclick)
    if m:
        return m.group(1)
    # Fall back to token in url
    m2 = re.search(r"[?&]id=([^&\"']+)", url)
    if m2:
        return m2.group(1)[:40]
    return url[-40:]


class HMTInAdapter(BaseAdapter):
    domain = "hmtwatches.in"

    def discover(self) -> list[Product]:
        """Discover all Gandaberunda and Kannadiga products via collection filter and search."""
        logger.info("[hmtwatches.in] Starting discovery (collection_id=%d and search)", GANDABERUNDA_COLLECTION_ID)
        self.last_error = None
        all_products: list[Product] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()

        # Step 1: Collection filter API (e.g. Collection 64 includes Heritage/Gandaberunda/Kannadiga)
        page = 1
        max_pages = 5  # Sufficient to cover all pages of collection 64
        empty_pages = 0

        while page <= max_pages:
            html = self._post_collection(page)
            if html is None:
                if page == 1:
                    self.last_error = f"Collection API request failed on page {page}"
                    logger.warning("[hmtwatches.in] Collection API failed on initial page %d", page)
                break

            if not html.strip():
                break

            soup = BeautifulSoup(html, "lxml")
            raw_cards = len(soup.select(".bc_p_item"))
            if raw_cards == 0:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                page += 1
                continue

            products = self._parse_listing_html(html)

            new_count = 0
            for p in products:
                norm_name = p.name.strip().lower()
                if p.product_id in seen_ids or (not norm_name.endswith("..") and norm_name in seen_names):
                    continue
                seen_ids.add(p.product_id)
                if not norm_name.endswith(".."):
                    seen_names.add(norm_name)
                all_products.append(p)
                new_count += 1

            logger.info("[hmtwatches.in] Collection page %d: found %d target products (%d new) out of %d total", page, len(products), new_count, raw_cards)

            # If fewer than 12 raw cards returned, that was the last page of the collection
            if raw_cards < 12:
                break
            page += 1
            time.sleep(0.5)

        # Step 2: Search queries as fallback or supplement if few products discovered
        if len(all_products) < 14:
            for query in ("kannadiga", "gandaberunda"):
                time.sleep(1.0)
                search_html = self._fetch_search(query)
                if search_html:
                    search_prods = self._parse_listing_html(search_html)
                    added = 0
                    for p in search_prods:
                        norm_name = p.name.strip().lower()
                        if p.product_id in seen_ids or (not norm_name.endswith("..") and norm_name in seen_names):
                            continue
                        seen_ids.add(p.product_id)
                        if not norm_name.endswith(".."):
                            seen_names.add(norm_name)
                        all_products.append(p)
                        added += 1
                    if added > 0:
                        logger.info("[hmtwatches.in] Search '%s': added %d additional products", query, added)

        logger.info("[hmtwatches.in] Discovery complete: %d products total", len(all_products))
        return all_products

    def _fetch_search(self, query: str) -> Optional[str]:
        """Fetch search results page for a query string."""
        url = f"{SEARCH_API}?keys={query}"
        resp = fetch(url)
        if resp and resp.status_code == 200:
            return resp.text
        return None

    def _post_collection(self, page: int) -> Optional[str]:
        """Call the filter_products_collections endpoint."""
        data = {
            "collection_val": str(GANDABERUNDA_COLLECTION_ID),
            "load_more_count": str(page),
            "price_filter": "",
            "availability_filter": "0",
            "gender_filter": "",
            "discount_filter": "",
            "collection_filter": "",
            "movement_filter": "",
        }
        resp = fetch(COLLECTION_API, method="POST", data=data, headers=_CSRF_HEADERS)
        if resp is None:
            return None
        try:
            payload = resp.json()
            if payload.get("status"):
                return payload.get("html", "")
        except Exception as exc:
            logger.warning("[hmtwatches.in] JSON parse error from collection API: %s", exc)
        return None

    def _parse_listing_html(self, html: str) -> list[Product]:
        """Parse the HTML fragment returned by the collection API."""
        soup = BeautifulSoup(html, "lxml")
        products: list[Product] = []

        for item in soup.select(".bc_p_item"):
            name_tag = item.select_one(".bc_p_name")
            img_link = item.select_one("a.bc_p_img")

            raw_url = None
            if name_tag and name_tag.get("href") and name_tag.get("href") != "#":
                raw_url = name_tag["href"]
            elif img_link and img_link.get("href"):
                raw_url = img_link["href"]

            if not raw_url:
                continue

            url = normalize_url(raw_url)
            span = name_tag.select_one("span") if name_tag else None
            name = clean_product_name(span.get_text(strip=True) if span else (name_tag.get_text(strip=True) if name_tag else ""))

            # Filter: only target watch variants (Gandaberunda or Kannadiga)
            if not is_target_watch(name):
                continue

            # Price
            price_tag = item.select_one(".bc_p_detail p")
            price = clean_product_name(price_tag.get_text(strip=True)) if price_tag else None

            # Availability from card
            card_res = classify_from_html(item, context="in_card")
            product_id = _extract_product_id(item, url)
            model_ref = extract_model_ref(name)

            last_rel = card_res.state if card_res.state != AvailabilityState.UNKNOWN else None

            prod = Product(
                domain=self.domain,
                product_id=product_id,
                name=name,
                url=url,
                price=price,
                model_ref=model_ref,
                availability=card_res.state,
                availability_reason=card_res.reason,
                first_seen=utcnow(),
                last_reliable_availability=last_rel,
            )
            products.append(prod)

        return products

    def check_product(self, product: Product) -> Product:
        """Re-check a single product's availability from its product detail page."""
        now = utcnow()
        product.last_checked = now
        normalized_url = normalize_url(product.url)
        product.url = normalized_url

        resp = fetch(normalized_url)
        if resp is None:
            logger.warning("[hmtwatches.in] Failed to fetch %s", normalized_url)
            product.availability = AvailabilityState.UNKNOWN
            product.availability_reason = "fetch_failed"
            return product

        product.last_successful_check = now
        soup = BeautifulSoup(resp.text, "lxml")

        # Resolve full untruncated product name if available on detail page
        title_el = soup.select_one("h3.product-title, h1.product-title, .product_name")
        if title_el:
            full_name = clean_product_name(title_el.get_text(strip=True))
            if is_target_watch(full_name) and not full_name.endswith(".."):
                product.name = full_name
                product.model_ref = extract_model_ref(full_name)

        # Update price if found
        price_tag = soup.select_one("h4.price, .cost, .product_cost, h4")
        if price_tag:
            p_text = clean_product_name(price_tag.get_text(strip=True))
            if "mrp" in p_text.lower() or "rs" in p_text.lower() or "₹" in p_text:
                product.price = p_text

        # Classify availability
        res = classify_from_html(soup, context="in_detail")
        product.availability = res.state
        product.availability_reason = res.reason
        if res.state != AvailabilityState.UNKNOWN:
            product.last_reliable_availability = res.state

        return product
