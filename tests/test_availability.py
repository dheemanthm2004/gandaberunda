"""Tests for availability classification and safety rules."""
from bs4 import BeautifulSoup
import pytest

from hmt_sentinel.availability import (
    AvailabilityResult,
    classify_from_flags,
    classify_from_html,
)
from hmt_sentinel.models import AvailabilityState


def test_classify_from_flags_in_stock():
    res = classify_from_flags(in_stock=True, is_buyable=True, current_stock=5)
    assert res.state == AvailabilityState.IN_STOCK


def test_classify_from_flags_out_of_stock_current_stock_zero():
    res = classify_from_flags(in_stock=True, is_buyable=True, current_stock=0)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "current_stock=0" in res.reason


def test_classify_from_flags_out_of_stock_not_buyable():
    res = classify_from_flags(in_stock=True, is_buyable=False)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "is_buyable=False" in res.reason


def test_classify_from_flags_out_of_stock_in_stock_false():
    res = classify_from_flags(in_stock=False)
    assert res.state == AvailabilityState.OUT_OF_STOCK


def test_classify_from_flags_coming_soon():
    res = classify_from_flags(is_coming_soon=True)
    assert res.state == AvailabilityState.COMING_SOON

    res2 = classify_from_flags(raw_status="Coming Soon")
    assert res2.state == AvailabilityState.COMING_SOON


def test_classify_from_flags_unknown():
    res = classify_from_flags()
    assert res.state == AvailabilityState.UNKNOWN


def test_classify_from_html_in_stock():
    html = """
    <div class="product">
        <h1>HMT Gandaberunda</h1>
        <button class="add-to-cart">Add to Cart</button>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.IN_STOCK
    assert "cart_button_enabled" in res.reason


def test_classify_from_html_out_of_stock_explicit_button():
    html = """
    <div class="product">
        <h1>HMT Gandaberunda</h1>
        <button disabled class="sb-wl-button">Out of Stock</button>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "explicit_oos_button" in res.reason


def test_classify_from_html_out_of_stock_div():
    html = """
    <div class="bc_p_item">
        <div class="bc_p_detail">
            <div class="outofstock"><p>Out of Stock</p></div>
        </div>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "outofstock_div" in res.reason


def test_classify_from_html_coming_soon_div():
    html = """
    <div class="bc_p_item">
        <div class="bc_p_detail">
            <div class="outofstock"><p><strong>Coming Soon</strong></p></div>
        </div>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.COMING_SOON
    assert "coming_soon" in res.reason


def test_classify_from_html_disabled_cart_button():
    html = """
    <div class="product">
        <button class="add_to_cart" disabled>Add to Cart</button>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "cart_disabled" in res.reason


def test_classify_from_html_notify_me_only():
    html = """
    <div class="product">
        <span onclick="notifyMe(1216)">Notify Me</span>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.OUT_OF_STOCK
    assert "notify_me" in res.reason


def test_classify_from_html_conflict_cart_and_oos():
    # Both 'Add to Cart' button and 'Sold Out' text -> must result in UNKNOWN
    html = """
    <div class="product">
        <p class="badge">Sold Out</p>
        <button class="btn add-to-cart">Add to Cart</button>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.UNKNOWN
    assert "conflict" in res.reason


def test_classify_from_html_conflict_cart_and_coming_soon():
    html = """
    <div class="product">
        <p class="badge">Coming Soon</p>
        <button class="btn add-to-cart">Add to Cart</button>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    assert res.state == AvailabilityState.UNKNOWN
    assert "conflict" in res.reason


def test_classify_from_html_no_conclusive_evidence():
    html = """
    <div class="product">
        <h1>HMT Gandaberunda</h1>
        <p>Price: Rs 2499</p>
        <p>A classic watch with two-headed eagle design.</p>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    res = classify_from_html(soup)
    # Visible price and successful page loading does NOT imply in stock!
    assert res.state == AvailabilityState.UNKNOWN
    assert "no_conclusive_evidence" in res.reason
