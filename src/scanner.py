from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "deals.json"
HTML_PATH = ROOT / "docs" / "index.html"

KEEPA_DEAL_URL = "https://api.keepa.com/deal"
KEEPA_EPOCH_OFFSET_MINUTES = 21_564_000

PRICE_TYPE_NAMES = {
    0: "Amazon",
    1: "Marketplace New",
    8: "Lightning Deal",
    9: "Amazon Warehouse",
    18: "Buy Box",
}


@dataclass
class Deal:
    asin: str
    title: str
    price_type: int
    price_type_name: str
    current_price: float
    normal_price_90d: float
    discount_percent: float
    savings: float
    tier: str
    score: int
    detected_at: str
    changed_at: str | None
    amazon_url: str


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def keepa_time_to_iso(value: int | None) -> str | None:
    if value is None or value < 0:
        return None
    unix_seconds = (value + KEEPA_EPOCH_OFFSET_MINUTES) * 60
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


def safe_index(values: Any, index: int, default: int = -1) -> int:
    if not isinstance(values, list) or index < 0 or index >= len(values):
        return default
    value = values[index]
    return value if isinstance(value, int) else default


def extract_deal(raw: dict[str, Any], price_type: int, config: dict[str, Any]) -> Deal | None:
    current_cents = safe_index(raw.get("current"), price_type)
    if current_cents <= 0:
        return None

    range_index = int(config.get("comparison_range", 3))
    delta_rows = raw.get("delta") or []
    percent_rows = raw.get("deltaPercent") or []

    delta_cents = -1
    discount = -1
    if 0 <= range_index < len(delta_rows):
        delta_cents = safe_index(delta_rows[range_index], price_type)
    if 0 <= range_index < len(percent_rows):
        discount = safe_index(percent_rows[range_index], price_type)

    # Keepa defines delta as comparison-period average/reference minus current.
    # For Lightning/Prime/Warehouse, Keepa uses Amazon/New as the reference.
    if delta_cents <= 0 or discount < 0:
        return None

    normal_cents = current_cents + delta_cents
    if normal_cents <= current_cents:
        return None

    computed_discount = (1 - (current_cents / normal_cents)) * 100
    # Keepa's integer percentage can differ slightly because of rounding. Use the
    # price-derived value for transparent deal math.
    discount_percent = round(computed_discount, 2)
    min_discount = float(config["minimum_discount_percent"])
    if discount_percent < min_discount:
        return None

    current_price = current_cents / 100.0
    max_current = float(config.get("max_current_price", 5000))
    if current_price > max_current:
        return None

    normal_price = normal_cents / 100.0
    savings = normal_price - current_price

    near_free = (
        current_price <= float(config["near_free_max_price"])
        and normal_price >= float(config["near_free_min_normal_price"])
    )
    pricing_error = discount_percent >= float(config["pricing_error_percent"])

    if near_free and discount_percent >= 95:
        tier = "NEAR FREE / POSSIBLE PRICING ERROR"
    elif pricing_error:
        tier = "POSSIBLE PRICING ERROR"
    else:
        tier = "90%+ EXTREME DROP"

    score = score_deal(discount_percent, current_price, normal_price, near_free)

    asin = str(raw.get("asin", "")).strip()
    if not asin:
        return None

    return Deal(
        asin=asin,
        title=str(raw.get("title") or asin),
        price_type=price_type,
        price_type_name=PRICE_TYPE_NAMES.get(price_type, f"Type {price_type}"),
        current_price=round(current_price, 2),
        normal_price_90d=round(normal_price, 2),
        discount_percent=discount_percent,
        savings=round(savings, 2),
        tier=tier,
        score=score,
        detected_at=datetime.now(timezone.utc).isoformat(),
        changed_at=keepa_time_to_iso(raw.get("creationDate")),
        amazon_url=f"https://www.amazon.com/dp/{asin}",
    )


def score_deal(discount: float, current: float, normal: float, near_free: bool) -> int:
    # Discount is the primary signal. Near-free and absolute savings break ties.
    score = 80 + min(15, max(0, int((discount - 90) * 1.5)))
    if discount >= 99:
        score += 4
    elif discount >= 97:
        score += 3
    elif discount >= 95:
        score += 2

    if near_free:
        score += 5
    elif current <= 10 and normal >= 100:
        score += 3

    if normal - current >= 500:
        score += 2
    elif normal - current >= 100:
        score += 1

    return min(100, score)


def query_keepa(api_key: str, price_type: int, page: int, config: dict[str, Any]) -> dict[str, Any]:
    max_cents = int(float(config.get("max_current_price", 5000)) * 100)
    selection = {
        "page": page,
        "domainId": int(config.get("domain_id", 1)),
        "priceTypes": [price_type],
        "dateRange": int(config.get("comparison_range", 3)),
        "isRangeEnabled": True,
        "currentRange": [1, max_cents],
        "deltaPercentRange": [int(config["minimum_discount_percent"]), 100],
        "isFilterEnabled": True,
        "filterErotic": True,
        "singleVariation": True,
        "sortType": 4,
    }
    response = requests.post(
        KEEPA_DEAL_URL,
        params={"key": api_key},
        json=selection,
        headers={"Accept-Encoding": "gzip", "User-Agent": "amazon-extreme-deal-finder/1.0"},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(f"Keepa API error: {payload['error']}")
    return payload


def scan(api_key: str, config: dict[str, Any]) -> list[Deal]:
    found: list[Deal] = []
    pages = max(1, int(config.get("pages_per_price_type", 1)))

    for price_type in config.get("price_types", [0]):
        for page in range(pages):
            payload = query_keepa(api_key, int(price_type), page, config)
            rows = ((payload.get("deals") or {}).get("dr") or [])
            for raw in rows:
                deal = extract_deal(raw, int(price_type), config)
                if deal:
                    found.append(deal)
            if len(rows) < 150:
                break

    return dedupe_and_sort(found, int(config.get("max_results", 250)))


def dedupe_and_sort(deals: Iterable[Deal], limit: int) -> list[Deal]:
    # If the same ASIN appears in multiple feeds, keep the cheapest/biggest drop.
    best: dict[str, Deal] = {}
    for deal in deals:
        prior = best.get(deal.asin)
        if prior is None or (
            deal.discount_percent,
            -deal.current_price,
            deal.score,
        ) > (
            prior.discount_percent,
            -prior.current_price,
            prior.score,
        ):
            best[deal.asin] = deal

    ranked = sorted(
        best.values(),
        key=lambda d: (d.score, d.discount_percent, d.savings, -d.current_price),
        reverse=True,
    )
    return ranked[:limit]


def write_json(deals: list[Deal], config: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "minimum_discount_percent": config["minimum_discount_percent"],
        "count": len(deals),
        "deals": [asdict(d) for d in deals],
    }
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_html(deals: list[Deal], config: dict[str, Any]) -> None:
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in deals:
        tier_class = "near" if "NEAR FREE" in d.tier else "error" if "PRICING ERROR" in d.tier else "extreme"
        rows.append(
            f"""
            <article class="deal {tier_class}">
              <div class="badge">{html.escape(d.tier)}</div>
              <h2>{html.escape(d.title)}</h2>
              <div class="numbers">
                <div><span>NOW</span><strong>${d.current_price:,.2f}</strong></div>
                <div><span>90-DAY REFERENCE</span><strong>${d.normal_price_90d:,.2f}</strong></div>
                <div><span>DROP</span><strong>{d.discount_percent:.2f}%</strong></div>
                <div><span>SAVE</span><strong>${d.savings:,.2f}</strong></div>
              </div>
              <p class="meta">Score {d.score}/100 · {html.escape(d.price_type_name)} · ASIN {html.escape(d.asin)}</p>
              <a class="button" href="{html.escape(d.amazon_url)}" target="_blank" rel="noopener noreferrer">Open on Amazon</a>
            </article>
            """
        )

    empty = "<p class='empty'>No 90%+ drops were found in this scan. The scanner is working; extreme pricing errors are naturally rare.</p>" if not rows else ""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    min_discount = config["minimum_discount_percent"]
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Amazon Extreme Deal Finder</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
body {{ margin:0; background:#0b0d10; color:#f4f6f8; }}
header {{ padding:36px 20px 22px; max-width:1100px; margin:auto; }}
h1 {{ margin:0 0 8px; font-size:clamp(32px,6vw,58px); letter-spacing:-2px; }}
.sub {{ color:#aab2bd; font-size:18px; }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:18px; }}
.pill {{ border:1px solid #303641; border-radius:999px; padding:8px 12px; color:#d7dce2; }}
main {{ max-width:1100px; margin:auto; padding:12px 20px 50px; display:grid; grid-template-columns:repeat(auto-fit,minmax(310px,1fr)); gap:16px; }}
.deal {{ border:1px solid #282d35; border-radius:18px; padding:20px; background:#12151a; box-shadow:0 10px 34px rgba(0,0,0,.18); }}
.deal.near {{ border-width:2px; }}
.badge {{ display:inline-block; font-size:12px; font-weight:800; letter-spacing:.6px; padding:7px 9px; border-radius:999px; background:#252a32; }}
h2 {{ font-size:19px; line-height:1.35; margin:14px 0 18px; }}
.numbers {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.numbers div {{ background:#0d1014; border-radius:12px; padding:12px; }}
.numbers span {{ display:block; color:#8d96a2; font-size:10px; font-weight:800; margin-bottom:3px; }}
.numbers strong {{ font-size:20px; }}
.meta {{ color:#929ba6; font-size:13px; margin:16px 0; }}
.button {{ display:block; text-align:center; text-decoration:none; font-weight:800; color:#111; background:#f4f6f8; border-radius:12px; padding:12px; }}
.empty {{ grid-column:1/-1; color:#aab2bd; border:1px dashed #343b46; border-radius:18px; padding:28px; }}
footer {{ max-width:1100px; margin:auto; padding:0 20px 40px; color:#737d89; font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>Amazon Extreme Deals</h1>
  <div class="sub">Only products calculated at {min_discount}%+ below their 90-day reference price.</div>
  <div class="summary">
    <div class="pill">{len(deals)} deals found</div>
    <div class="pill">Updated {generated}</div>
    <div class="pill">95%+ flagged as possible pricing errors</div>
    <div class="pill">$5 or less can qualify as near-free</div>
  </div>
</header>
<main>{''.join(rows)}{empty}</main>
<footer>Pricing errors can be corrected or canceled before shipment. Verify the product, seller, quantity, shipping, coupon requirements, and final checkout price before purchasing.</footer>
</body></html>"""
    HTML_PATH.write_text(body, encoding="utf-8")


def main() -> int:
    config = load_config()
    api_key = os.environ.get("KEEPA_API_KEY", "").strip()
    if not api_key:
        print("ERROR: KEEPA_API_KEY is not set.", file=sys.stderr)
        return 2

    deals = scan(api_key, config)
    write_json(deals, config)
    render_html(deals, config)
    print(f"Found {len(deals)} qualifying 90%+ deals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
