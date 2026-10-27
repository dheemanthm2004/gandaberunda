"""Tests for discovery mechanisms and adapters using fixtures and mocks."""
import json
import pytest
import responses
from bs4 import BeautifulSoup

from hmt_sentinel.adapters.hmt_in import HMTInAdapter
from hmt_sentinel.adapters.hmt_store import HMTStoreAdapter
from hmt_sentinel.discovery import DiscoveryService
from hmt_sentinel.models import AvailabilityState


SAMPLE_NEXT_DATA_HOME = {
    "props": {
        "pageProps": {
            "allCollections": [
                {
                    "name": "GandaBerunda ",
                    "id": "6581423c-58b1-45c3-8695-202718942368",
                },
                {
                    "name": "Kohinoor",
                    "id": "c757ecc9-31e2-4cf7-bcb1-9b29f5c57c41",
                },
            ],
            "products": [
                {
                    "itemSku": "sku-ganda-home-1",
                    "itemDetails": {
                        "name": "HMT Women's Gandaberunda JLGG - 01 White",
                        "sku": "sku-ganda-home-1",
                        "mrp": 2599,
                        "sellingPrice": 2599,
                        "buyingOptions": {
                            "singlePurchase": {
                                "availability": {
                                    "inStock": False,
                                    "isBuyable": False,
                                    "currentStock": 0,
                                }
                            }
                        },
                    },
                },
                {
                    "itemSku": "sku-kohinoor-1",
                    "itemDetails": {
                        "name": "HMT Kohinoor Quartz",
                        "sku": "sku-kohinoor-1",
                    },
                },
            ],
        }
    }
}

SAMPLE_NEXT_DATA_COLLECTION = {
    "props": {
        "pageProps": {
            "collectionName": "GandaBerunda",
            "initialProducts": [
                {
                    "itemSku": "sku-ganda-col-2",
                    "itemDetails": {
                        "name": "HMT Men's Gandaberunda JLGL 01",
                        "sku": "sku-ganda-col-2",
                        "mrp": 2799,
                        "sellingPrice": 2799,
                        "buyingOptions": {
                            "singlePurchase": {
                                "availability": {
                                    "inStock": True,
                                    "isBuyable": True,
                                    "currentStock": 3,
                                }
                            }
                        },
                    },
                }
            ],
        }
    }
}

SAMPLE_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://www.hmtwatches.store/collection/6581423c-58b1-45c3-8695-202718942368/GandaBerunda%20</loc>
    </url>
    <url>
        <loc>https://www.hmtwatches.store/collection/c757ecc9-31e2-4cf7-bcb1-9b29f5c57c41/Kohinoor</loc>
    </url>
    <url>
        <loc>https://www.hmtwatches.store/product/sku-ganda-home-1</loc>
    </url>
</urlset>
"""

SAMPLE_IN_API_HTML = """
<div class="row all_watches">
    <div class="bc_p_item">
        <a class="bc_p_name" href="https://www.hmtwatches.in/product_overview?id=token1">
            <span>HMT Women's Gandab..</span>
        </a>
        <div class="bc_p_detail">
            <p>RS. 2499</p>
            <div class="outofstock"><strong>Coming Soon</strong></div>
        </div>
        <span onclick="notifyMe(1216)"></span>
    </div>
    <div class="bc_p_item">
        <a class="bc_p_name" href="https://www.hmtwatches.in/product_overview?id=token2">
            <span>HMT Men's Gandaber..</span>
        </a>
        <div class="bc_p_detail">
            <p>RS. 2699</p>
            <div class="outofstock"><strong>Out of Stock</strong></div>
        </div>
        <span onclick="notifyMe(1217)"></span>
    </div>
    <div class="bc_p_item">
        <a class="bc_p_name" href="https://www.hmtwatches.in/product_overview?id=token3">
            <span>HMT Galaxy VG3L22 ..</span>
        </a>
        <div class="bc_p_detail">
            <p>RS. 1799</p>
        </div>
    </div>
</div>
"""


@responses.activate
def test_hmt_store_discovery():
    # Mock homepage
    home_html = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(SAMPLE_NEXT_DATA_HOME)}</script></head><body></body></html>'
    responses.add(
        responses.GET,
        "https://www.hmtwatches.store/",
        body=home_html,
        status=200,
    )

    # Mock sitemap
    responses.add(
        responses.GET,
        "https://www.hmtwatches.store/sitemap.xml",
        body=SAMPLE_SITEMAP_XML,
        status=200,
    )

    # Mock collection
    col_html = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(SAMPLE_NEXT_DATA_COLLECTION)}</script></head><body></body></html>'
    responses.add(
        responses.GET,
        "https://www.hmtwatches.store/collection/6581423c-58b1-45c3-8695-202718942368/GandaBerunda",
        body=col_html,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://www.hmtwatches.store/collection/6581423c-58b1-45c3-8695-202718942368/GandaBerunda%20",
        body=col_html,
        status=200,
    )

    adapter = HMTStoreAdapter()
    products = adapter.discover()

    assert len(products) == 2
    skus = {p.product_id for p in products}
    assert "sku-ganda-home-1" in skus
    assert "sku-ganda-col-2" in skus

    # Verify attributes
    p1 = next(p for p in products if p.product_id == "sku-ganda-home-1")
    assert p1.price == "₹2599"
    assert p1.availability == AvailabilityState.OUT_OF_STOCK
    assert p1.domain == "hmtwatches.store"

    p2 = next(p for p in products if p.product_id == "sku-ganda-col-2")
    assert p2.price == "₹2799"
    assert p2.availability == AvailabilityState.IN_STOCK


@responses.activate
def test_hmt_store_discovery_failed_requests():
    responses.add(responses.GET, "https://www.hmtwatches.store/", status=500)
    responses.add(responses.GET, "https://www.hmtwatches.store/sitemap.xml", status=500)

    adapter = HMTStoreAdapter()
    products = adapter.discover()
    assert len(products) == 0
    assert adapter.last_error is not None


@responses.activate
def test_hmt_store_check_product():
    pdp_next_data = {
        "props": {
            "pageProps": {
                "catalog": {
                    "name": "HMT Women's Gandaberunda JLGG - 01 White",
                    "variantsDetails": [
                        {
                            "sku": "sku-1",
                            "variantAttributes": {
                                "price": {"sellingPrice": 2599},
                                "buyingOptions": {
                                    "singlePurchase": {
                                        "availability": {
                                            "inStock": True,
                                            "isBuyable": True,
                                            "currentStock": 5,
                                        }
                                    }
                                },
                            },
                        }
                    ],
                }
            }
        }
    }
    pdp_html = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(pdp_next_data)}</script></head><body></body></html>'
    responses.add(
        responses.GET,
        "https://www.hmtwatches.store/product/sku-1",
        body=pdp_html,
        status=200,
    )

    adapter = HMTStoreAdapter()
    prod = adapter._product_from_item_details("sku-1", {}, "HMT Gandaberunda")
    checked = adapter.check_product(prod)
    assert checked.availability == AvailabilityState.IN_STOCK
    assert checked.price == "₹2599"


@responses.activate
def test_hmt_in_discovery_and_pagination():
    # Page 1 returns 2 gandaberunda products + 1 non-gandaberunda (3 total items < 12 triggers completion)
    responses.add(
        responses.POST,
        "https://www.hmtwatches.in/filter_products_collections",
        json={"status": True, "html": SAMPLE_IN_API_HTML},
        status=200,
    )

    adapter = HMTInAdapter()
    products = adapter.discover()

    assert len(products) == 2
    names = [p.name for p in products]
    assert "HMT Women's Gandab.." in names
    assert "HMT Men's Gandaber.." in names

    p1 = products[0]
    assert p1.product_id == "1216"
    assert p1.availability == AvailabilityState.COMING_SOON
    assert p1.domain == "hmtwatches.in"

    p2 = products[1]
    assert p2.product_id == "1217"
    assert p2.availability == AvailabilityState.OUT_OF_STOCK


@responses.activate
def test_hmt_in_check_product_untruncates_name():
    detail_html = """
    <html>
        <body>
            <h3 class="product-title">HMT Women's Gandaberunda JLGL 01</h3>
            <h4 class="product_cost">MRP2499</h4>
            <div class="outofstock"><p>Out Of Stock</p></div>
        </body>
    </html>
    """
    responses.add(
        responses.GET,
        "https://www.hmtwatches.in/product_overview?id=token1",
        body=detail_html,
        status=200,
    )

    adapter = HMTInAdapter()
    from hmt_sentinel.models import Product
    prod = Product(
        domain="hmtwatches.in",
        product_id="1216",
        name="HMT Women's Gandab..",
        url="https://www.hmtwatches.in/product_overview?id=token1",
    )

    checked = adapter.check_product(prod)
    assert checked.name == "HMT Women's Gandaberunda JLGL 01"
    assert checked.model_ref == "JLGL 01"
    assert checked.price == "MRP2499"
    assert checked.availability == AvailabilityState.OUT_OF_STOCK


def test_discovery_service_coordinates_both(mocker):
    store_mock = mocker.MagicMock(spec=HMTStoreAdapter)
    store_mock.domain = "hmtwatches.store"
    store_mock.discover.return_value = []
    store_mock.last_error = None

    in_mock = mocker.MagicMock(spec=HMTInAdapter)
    in_mock.domain = "hmtwatches.in"
    in_mock.discover.return_value = []
    in_mock.last_error = None

    service = DiscoveryService(store_adapter=store_mock, in_adapter=in_mock)
    reports = service.discover_all(enable_store=True, enable_in=True)

    assert "hmtwatches.store" in reports
    assert "hmtwatches.in" in reports
    assert store_mock.discover.called
    assert in_mock.discover.called
