from src.scanner import extract_deal, score_deal

CONFIG = {
    "minimum_discount_percent": 90,
    "pricing_error_percent": 95,
    "near_free_max_price": 5.0,
    "near_free_min_reference_price": 20.0,
    "max_current_price": 5000.0,
}


def test_near_free_pricing_error():
    raw = {
        "asin": "B000TEST01",
        "title": "Test Product",
        "price": "1.99",
        "originalPrice": "99.99",
        "discountPercent": 98,
        "url": "https://www.amazon.com/dp/B000TEST01",
    }
    deal = extract_deal(raw, CONFIG)
    assert deal is not None
    assert deal.discount_percent > 97
    assert "NEAR FREE" in deal.tier
    assert deal.current_price == 1.99


def test_rejects_under_90_percent():
    raw = {
        "asin": "B000TEST02",
        "title": "Not Extreme",
        "price": 15.0,
        "originalPrice": 100.0,
        "discountPercent": 85,
    }
    assert extract_deal(raw, CONFIG) is None


def test_computes_discount_from_prices_not_claim():
    raw = {
        "asin": "B000TEST03",
        "title": "Math Wins",
        "price": 9.99,
        "originalPrice": 199.99,
        "discountPercent": 10,
    }
    deal = extract_deal(raw, CONFIG)
    assert deal is not None
    assert deal.discount_percent >= 95


def test_reported_discount_fallback():
    raw = {
        "asin": "B000TEST04",
        "title": "No List Price",
        "price": 5.0,
        "discountPercent": 95,
    }
    deal = extract_deal(raw, CONFIG)
    assert deal is not None
    assert deal.reference_price == 100.0


def test_score_caps_at_100():
    assert score_deal(99.9, 0.99, 999.99, True) == 100
