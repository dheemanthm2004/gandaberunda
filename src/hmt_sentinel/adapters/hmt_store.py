"""Adapter for hmtwatches.store (Amazon SmartBiz / Next.js platform).

Discovery strategy:
  1. Primary Entry: Homepage (https://www.hmtwatches.store/)
     Parses Next.js JSON (__NEXT_DATA__) to find:
     - allCollections: finds Gandaberunda collection(s) dynamically
     - products / productSkuDictionary: featured products matching Gandaberunda
  2. Collection Exploration:
     Fetches discovered Gandaberunda collection page(s) (e.g. /collection/.../GandaBerunda)
     and extracts initialProducts.
  3. Sitemap Discovery:
     Fetches /sitemap.xml and extracts all collection and product URLs matching Gandaberunda.
  4. HTML / Regex fallback:
     Parses product links /product/{UUID} from any page.

Availability Strategy:
  - Fetches product detail page (https://www.hmtwatches.store/product/{productId})
  - Extracts structured Next.js __NEXT_DATA__ catalog:
    variantsDetails[0].variantAttributes.buyingOptions.singlePurchase.availability:
    inStock, isBuyable, currentStock.
  - HTML signals:
    - Button text 'Out of Stock' with disabled attribute.
    - Enabled 'Add to Cart' or 'Buy Now'.
  - Conservative classification via hmt_sentinel.availability.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hmt_sentinel.adapters.base import BaseAdapter, fetch
from hmt_sentinel.availability import (
    classify_from_flags,
    classify_from_html,
)
from hmt_sentinel.matching import (
    clean_product_name,
    extract_model_ref,
    is_gandaberunda,
    normalize_url,
)
from hmt_sentinel.models import AvailabilityState, Product, utcnow

logger = logging.getLogger(__name__)

BASE_URL = "https://www.hmtwatches.store"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"


# SEO crawler header used by Amazon SmartBiz Next.js to server-render full collection listings
_SEO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Google-InspectionTool/1.0;) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _extract_next_data(html: str) -> Optional[dict]:
    """Extract and parse the __NEXT_DATA__ JSON script tag from HTML."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception as exc:
            logger.warning("[hmtwatches.store] Failed to parse __NEXT_DATA__ JSON: %s", exc)
    return None


class HMTStoreAdapter(BaseAdapter):
    domain = "hmtwatches.store"

    def discover(self) -> list[Product]:
        """Discover all Gandaberunda products on hmtwatches.store dynamically."""
        logger.info("[hmtwatches.store] Starting discovery")
        self.last_error = None
        products_by_id: dict[str, Product] = {}
        collections_to_visit: list[str] = []

        # Step 1: Check homepage Next.js data
        home_resp = fetch(BASE_URL)
        if home_resp is None:
            self.last_error = "Failed to fetch homepage"
            logger.warning("[hmtwatches.store] Failed to fetch homepage")
        else:
            home_data = _extract_next_data(home_resp.text)
            if home_data:
                page_props = home_data.get("props", {}).get("pageProps", {})

                # Find Gandaberunda collections in allCollections
                for col in page_props.get("allCollections", []):
                    col_name = col.get("name", "")
                    col_id = col.get("id") or col.get("collectionId")
                    if is_gandaberunda(col_name) and col_id:
                        col_url = f"{BASE_URL}/collection/{col_id}/{col_name.strip()}"
                        collections_to_visit.append(col_url)
                        logger.info("[hmtwatches.store] Found collection from home: %s (%s)", col_name, col_url)

                # Check featured products on home
                home_prods = page_props.get("products", [])
                for p in home_prods:
                    item_details = p.get("itemDetails", {})
                    name = clean_product_name(item_details.get("name") or p.get("name") or "")
                    if is_gandaberunda(name):
                        sku = str(p.get("itemSku") or item_details.get("sku") or item_details.get("primaryProductId") or "")
                        if sku:
                            prod = self._product_from_item_details(sku, item_details, name)
                            products_by_id[sku] = prod

        # Step 2: Check Sitemap for Gandaberunda collections & products
        sitemap_resp = fetch(SITEMAP_URL)
        if sitemap_resp:
            try:
                root = ET.fromstring(sitemap_resp.content)
                ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for loc_tag in root.findall(".//ns:loc", ns):
                    loc = loc_tag.text or ""
                    if "/collection/" in loc and is_gandaberunda(loc):
                        if loc not in collections_to_visit:
                            collections_to_visit.append(loc)
                            logger.info("[hmtwatches.store] Found collection from sitemap: %s", loc)
            except Exception as exc:
                logger.warning("[hmtwatches.store] Failed to parse sitemap: %s", exc)

        # Step 3: Visit each Gandaberunda collection page (using SEO pre-render headers to bypass client-only PLP filtering)
        for col_url in collections_to_visit:
            col_resp = fetch(col_url, headers=_SEO_HEADERS)
            if not col_resp:
                # Also try default headers as fallback
                col_resp = fetch(col_url)
            if not col_resp:
                continue

            soup = BeautifulSoup(col_resp.text, "lxml")
            col_data = _extract_next_data(col_resp.text)
            if col_data:
                page_props = col_data.get("props", {}).get("pageProps", {})

                # Check collectionProducts, initialProducts, products
                raw_product_lists = [
                    page_props.get("collectionProducts", []),
                    page_props.get("initialProducts", []),
                    page_props.get("products", []),
                ]
                for p_list in raw_product_lists:
                    for p in p_list:
                        item_details = p.get("itemDetails", {}) if isinstance(p.get("itemDetails"), dict) else p
                        name = clean_product_name(item_details.get("name") or p.get("name") or "")
                        sku = str(p.get("sku") or p.get("itemSku") or item_details.get("sku") or item_details.get("primaryProductId") or "")
                        if is_gandaberunda(name) and sku:
                            prod = self._product_from_item_details(sku, item_details, name)
                            products_by_id[sku] = prod

            # Fallback: parse direct HTML product links from rendered page
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                m = re.search(r"/product/([a-f0-9\-]{32,36})", href, re.IGNORECASE)
                if m:
                    sku = m.group(1)
                    link_text = clean_product_name(a_tag.get_text(strip=True))
                    if is_gandaberunda(link_text) and sku not in products_by_id:
                        prod = self._product_from_item_details(sku, {"name": link_text}, link_text)
                        products_by_id[sku] = prod

        # Step 4: If any products were found, check availability for any that are still UNKNOWN
        discovered_list = list(products_by_id.values())
        logger.info("[hmtwatches.store] Discovery complete: %d products found", len(discovered_list))
        return discovered_list

    def _product_from_item_details(self, sku: str, details: dict, name: str) -> Product:
        """Create a Product instance from SmartBiz itemDetails dict."""
        url = normalize_url(f"{BASE_URL}/product/{sku}")
        price = None
        selling_price = details.get("sellingPrice") or details.get("mrp")
        if selling_price:
            price = f"₹{selling_price}"

        model_ref = extract_model_ref(name)
        if not model_ref and details.get("modelNo"):
            model_ref = str(details.get("modelNo")).strip().upper()

        # Check availability flags if present
        availability = AvailabilityState.UNKNOWN
        reason = "discovered_from_listing"

        buying_opts = details.get("buyingOptions", {})
        if isinstance(buying_opts, dict):
            sp = buying_opts.get("singlePurchase", {})
            if isinstance(sp, dict):
                avail_info = sp.get("availability", {})
                if isinstance(avail_info, dict):
                    res = classify_from_flags(
                        in_stock=avail_info.get("inStock"),
                        is_buyable=avail_info.get("isBuyable"),
                        current_stock=avail_info.get("currentStock"),
                    )
                    availability = res.state
                    reason = res.reason

        last_rel = availability if availability != AvailabilityState.UNKNOWN else None

        return Product(
            domain=self.domain,
            product_id=sku,
            name=name,
            url=url,
            price=price,
            model_ref=model_ref,
            availability=availability,
            availability_reason=reason,
            first_seen=utcnow(),
            last_reliable_availability=last_rel,
        )

    def check_product(self, product: Product) -> Product:
        """Re-check a single product's availability from its product detail page."""
        now = utcnow()
        product.last_checked = now
        normalized_url = normalize_url(product.url)
        product.url = normalized_url

        resp = fetch(normalized_url)
        if resp is None:
            logger.warning("[hmtwatches.store] Failed to fetch product page: %s", normalized_url)
            product.availability = AvailabilityState.UNKNOWN
            product.availability_reason = "fetch_failed"
            return product

        product.last_successful_check = now
        soup = BeautifulSoup(resp.text, "lxml")

        # 1. Try structured Next.js data
        next_data = _extract_next_data(resp.text)
        if next_data:
            page_props = next_data.get("props", {}).get("pageProps", {})
            catalog = page_props.get("catalog", {})
            if catalog:
                cat_name = catalog.get("name")
                if cat_name:
                    product.name = clean_product_name(cat_name)
                    if not product.model_ref:
                        product.model_ref = extract_model_ref(product.name)

                variants = catalog.get("variantsDetails", [])
                if variants:
                    v_attr = variants[0].get("variantAttributes", {})
                    # Update price
                    p_info = v_attr.get("price", {})
                    if p_info.get("sellingPrice") or p_info.get("mrp"):
                        product.price = f"₹{p_info.get('sellingPrice') or p_info.get('mrp')}"

                    buying_opts = v_attr.get("buyingOptions", {})
                    if isinstance(buying_opts, dict):
                        sp = buying_opts.get("singlePurchase", {})
                        if isinstance(sp, dict):
                            avail = sp.get("availability", {})
                            if isinstance(avail, dict):
                                res = classify_from_flags(
                                    in_stock=avail.get("inStock"),
                                    is_buyable=avail.get("isBuyable"),
                                    current_stock=avail.get("currentStock"),
                                )
                                product.availability = res.state
                                product.availability_reason = f"store_json:{res.reason}"
                                if res.state != AvailabilityState.UNKNOWN:
                                    product.last_reliable_availability = res.state
                                return product

        # 2. Fallback to HTML classification
        html_res = classify_from_html(soup, context="store_html")
        product.availability = html_res.state
        product.availability_reason = html_res.reason
        if html_res.state != AvailabilityState.UNKNOWN:
            product.last_reliable_availability = html_res.state

        return product
