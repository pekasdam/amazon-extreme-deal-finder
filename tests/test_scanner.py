from src.scanner import extract_deal, score_deal

CONFIG = {
    "minimum_discount_percent": 90,
    "pricing_error_percent": 95,
    "near_free_max_price": 5.0,
    "near_free_min_normal_price": 20.0,
    "max_current_price": 5000.0,
    "comparison_range": 3,
}


def raw_deal(current=199, normal=9999, price_type=0):
    size = max(34, price_type + 1)
    current_arr = [-1] * size
    current_arr[price_type] = current
    delta = [[-1] * size for _ in range(4)]
    dp = [[-1] * size for _ in range(4)]
    delta[3][price_type] = normal - current
    dp[3][price_type] = round((normal - current) / normal * 100)
    return {
        "asin": "B000TEST01",
        "title": "Test Product",
        "current": current_arr,
        "delta": delta,
        "deltaPercent": dp,
        "creationDate": 7661010,
    }


def test_near_free_pricing_error():
    deal = extract_deal(raw_deal(199, 9999, 0), 0, CONFIG)
    assert deal is not None
    assert deal.discount_percent > 97
    assert "NEAR FREE" in deal.tier
    assert deal.current_price == 1.99


def test_rejects_under_90_percent():
    deal = extract_deal(raw_deal(1500, 10000, 0), 0, CONFIG)
    assert deal is None


def test_warehouse_price_type_index():
    deal = extract_deal(raw_deal(499, 15000, 9), 9, CONFIG)
    assert deal is not None
    assert deal.price_type_name == "Amazon Warehouse"


def test_score_caps_at_100():
    assert score_deal(99.9, 0.99, 999.99, True) == 100
