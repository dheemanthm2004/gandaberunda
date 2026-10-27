"""Tests for product matching and normalization."""
import pytest
from hmt_sentinel.matching import (
    clean_product_name,
    extract_model_ref,
    is_gandaberunda,
    normalize_url,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("HMT Gandaberunda", True),
        ("HMT Gandabherunda", True),
        ("gandaberunda", True),
        ("GANDABERUNDA", True),
        ("GANDABHERUNDA", True),
        ("HMT Ganda-berunda Men", True),
        ("HMT Ganda-bherunda", True),
        ("HMT Ganda Berunda White Dial", True),
        ("HMT Ganda_berunda", True),
        ("HMT Women's Gandab..", True),
        ("HMT Men's Gandaber..", True),
        ("HMT  Men's Gandabe..", True),
        ("HMT Women's Gandaberunda JLGG - 01 White", True),
        ("HMT Men's Gandaberunda JLGL 01", True),
        ("hmt gandaberunda leather strap", True),
        ("HMT Gandaberunda Gold Plated", True),
        # Irrelevant watches
        ("HMT Galaxy VG3L22", False),
        ("HMT Sona SLG 741", False),
        ("HMT Kohinoor Quartz", False),
        ("HMT Tareeq Tiffany Blue", False),
        ("HMT Sangam MGSS 06", False),
        ("HMT Stellar DASS 01", False),
        ("HMT Janata Automatic", False),
        ("HMT Pilot Black Dial", False),
        ("", False),
        ("Random text without the watch name", False),
    ],
)
def test_is_gandaberunda(text, expected):
    assert is_gandaberunda(text) is expected


def test_clean_product_name():
    assert clean_product_name("  HMT   Women&#039;s Gandaberunda   ") == "HMT Women's Gandaberunda"
    assert clean_product_name("&quot;Gandaberunda&quot;") == '"Gandaberunda"'
    assert clean_product_name("") == ""


def test_extract_model_ref():
    assert extract_model_ref("HMT Women's Gandaberunda JLGG - 01 White") == "JLGG 01"
    assert extract_model_ref("HMT Men's Gandaberunda JLGL 01") == "JLGL 01"
    assert extract_model_ref("HMT Gandaberunda JLSS 01 Yellow") == "JLSS 01"
    assert extract_model_ref("HMT Watch Without Model Code") is None


def test_normalize_url():
    # .store domain normalization
    assert normalize_url("https://hmtwatches.store/product/123/") == "https://www.hmtwatches.store/product/123"
    assert normalize_url("http://www.hmtwatches.store/product/123?ref=test") == "https://www.hmtwatches.store/product/123"

    # .in domain normalization
    in_url = "https://www.hmtwatches.in/product_overview?id=abc123token"
    assert normalize_url(in_url) == in_url
    assert normalize_url("http://hmtwatches.in/product_overview?id=abc123token/") == in_url

