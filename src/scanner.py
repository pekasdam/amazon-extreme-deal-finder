from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "deals.json"
HTML_PATH = ROOT / "docs" / "index.html"

APIFY_BASE_URL = "https://api.apify.com/v2/actors"


@dataclass
class Deal:
    asin: str
    title: str
    current_price: float
    reference_price: float
    discount_percent: float
    savings: float
    tier: str
    score: int
    detected_at: str
    amazon_url: str
    deal_type: str | None = None
    category: str | None = None
    prime_exclusive: bool | None = None
    reference_source: str = "Amazon deal reference price"


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def first_present(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def score_deal(discount: float, current: float, reference: float, near_free: bool) -> int:
    score = 80 + min(15, max(0, int((discount - 90) * 1.5)))
    if discount >= 99:
        score += 4
    elif discount >= 97:
        score += 3
    elif discount >= 95:
        score += 2

    if near_free:
        score += 5
    elif current <= 10 and reference >= 100:
        score += 3

    savings = reference - current
    if savings >= 500:
        score += 2
    elif savings >= 100:
        score += 1

    return min(100, score)


def extract_deal(raw: dict[str, Any], config: dict[str, Any]) -> Deal | None:
    asin = str(first_present(raw, "asin", "productAsin", "productId") or "").strip()
    if not asin:
        return None

    current = to_float(first_present(raw, "price", "currentPrice", "current_price"))
    if current is None or current <= 0:
        return None

    max_current = float(config.get("max_current_price", 5000))
    if current > max_current:
        return None

    reference = to_float(
        first_present(raw, "originalPrice", "listPrice", "list_price", "original_price")
    )
    reported_discount = to_float(
        first_present(raw, "discountPercent", "discount_percentage", "discountPercentValue")
    )

    if reference is not None and reference > current:
        discount = (1 - current / reference) * 100
        reference_source = "Amazon original/list price"
    elif reported_discount is not None and 0 < reported_discount < 100:
        discount = reported_discount
        reference = current / (1 - discount / 100)
        reference_source = "Amazon reported deal discount"
    else:
        return None

    discount = round(float(discount), 2)
    if discount < float(config.get("minimum_discount_percent", 90)):
        return None

    reference = round(float(reference), 2)
    current = round(float(current), 2)
    savings = round(max(0.0, reference - current), 2)

    near_free = (
        current <= float(config.get("near_free_max_price", 5.0))
        and reference >= float(config.get("near_free_min_reference_price", 20.0))
    )
    pricing_error = discount >= float(config.get("pricing_error_percent", 95))

    if near_free and discount >= 95:
        tier = "NEAR FREE / POSSIBLE PRICING ERROR"
    elif pricing_error:
        tier = "POSSIBLE PRICING ERROR"
    else:
        tier = "90%+ EXTREME DEAL"

    score = score_deal(discount, current, reference, near_free)
    title = str(first_present(raw, "title", "itemName", "name") or asin)
    amazon_url = str(first_present(raw, "url", "itemUrl", "productUrl") or f"https://www.amazon.com/dp/{asin}")

    prime_value = first_present(raw, "primeExclusive", "isPrimeExclusive", "prime_exclusive")
    prime_exclusive = prime_value if isinstance(prime_value, bool) else None

    return Deal(
        asin=asin,
        title=title,
        current_price=current,
        reference_price=reference,
        discount_percent=discount,
        savings=savings,
        tier=tier,
        score=score,
        detected_at=datetime.now(timezone.utc).isoformat(),
        amazon_url=amazon_url,
        deal_type=str(first_present(raw, "dealType", "deal_type") or "") or None,
        category=str(first_present(raw, "category", "categoryName") or "") or None,
        prime_exclusive=prime_exclusive,
        reference_source=reference_source,
    )


def query_apify(api_token: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    actor = str(config.get("apify_actor", "premiumscraper~amazon-products-scraper-today-deals"))
    max_products = max(1, int(config.get("max_results_per_scan", 2)))
    max_charge = float(config.get("max_total_charge_usd_per_run", 0.01))

    actor_input = {
        "prime_exclusive": False,
        "price_max": int(float(config.get("max_current_price", 5000))),
        "discount_min": int(float(config.get("minimum_discount_percent", 90))),
        "discount_max": 100,
        "max_products": max_products,
        "proxyCountry": "US",
        "include_raw": False,
    }

    url = f"{APIFY_BASE_URL}/{actor}/run-sync-get-dataset-items"
    response = requests.post(
        url,
        params={
            "clean": "1",
            "format": "json",
            "maxItems": max_products,
            "maxTotalChargeUsd": max_charge,
        },
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": "amazon-extreme-deal-finder/2.0",
        },
        json=actor_input,
        timeout=300,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected Apify response: {type(payload).__name__}")
    return [row for row in payload if isinstance(row, dict)]


def scan(api_token: str, config: dict[str, Any]) -> list[Deal]:
    rows = query_apify(api_token, config)
    found = [deal for raw in rows if (deal := extract_deal(raw, config)) is not None]
    return dedupe_and_sort(found, int(config.get("max_results_per_scan", 2)))


def dedupe_and_sort(deals: Iterable[Deal], limit: int) -> list[Deal]:
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
        "source": "Apify Amazon Today's Deals",
        "minimum_discount_percent": config["minimum_discount_percent"],
        "count": len(deals),
        "deals": [asdict(d) for d in deals],
    }
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_html(deals: list[Deal], config: dict[str, Any]) -> None:
    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for d in deals:
        tier_class = "near" if "NEAR FREE" in d.tier else "error" if "PRICING ERROR" in d.tier else "extreme"
        extra = " · ".join(x for x in [d.deal_type, d.category] if x)
        rows.append(
            f"""
            <article class="deal {tier_class}">
              <div class="badge">{html.escape(d.tier)}</div>
              <h2>{html.escape(d.title)}</h2>
              <div class="numbers">
                <div><span>NOW</span><strong>${d.current_price:,.2f}</strong></div>
                <div><span>REFERENCE</span><strong>${d.reference_price:,.2f}</strong></div>
                <div><span>DROP</span><strong>{d.discount_percent:.2f}%</strong></div>
                <div><span>SAVE</span><strong>${d.savings:,.2f}</strong></div>
              </div>
              <p class="meta">Score {d.score}/100 · ASIN {html.escape(d.asin)}{(' · ' + html.escape(extra)) if extra else ''}</p>
              <p class="source">Reference: {html.escape(d.reference_source)}</p>
              <a class="button" href="{html.escape(d.amazon_url)}" target="_blank" rel="noopener noreferrer">Open on Amazon</a>
            </article>
            """
        )

    empty = "<p class='empty'>No 90%+ Amazon Today's Deals were returned in this scan. Extreme pricing mistakes are rare and may disappear quickly.</p>" if not rows else ""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    min_discount = config["minimum_discount_percent"]
    max_results = config.get("max_results_per_scan", 2)
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
.meta,.source {{ color:#929ba6; font-size:13px; margin:12px 0; }}
.button {{ display:block; text-align:center; text-decoration:none; font-weight:800; color:#111; background:#f4f6f8; border-radius:12px; padding:12px; }}
.empty {{ grid-column:1/-1; color:#aab2bd; border:1px dashed #343b46; border-radius:18px; padding:28px; }}
footer {{ max-width:1100px; margin:auto; padding:0 20px 40px; color:#737d89; font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>Amazon Extreme Deals</h1>
  <div class="sub">Amazon Today's Deals filtered for {min_discount}%+ discounts and possible pricing errors.</div>
  <div class="summary">
    <div class="pill">{len(deals)} deals found</div>
    <div class="pill">Updated {generated}</div>
    <div class="pill">95%+ = possible pricing error</div>
    <div class="pill">$5 or less can qualify as near-free</div>
    <div class="pill">Free-budget mode: max {max_results} results/scan</div>
  </div>
</header>
<main>{''.join(rows)}{empty}</main>
<footer>Source: Amazon Today's Deals through Apify. A large advertised discount is not proof of a pricing error. Verify the product, seller, quantity, shipping, coupon requirements, and final checkout price before purchasing. Amazon or a seller may correct or cancel erroneous prices.</footer>
</body></html>"""
    HTML_PATH.write_text(body, encoding="utf-8")


def main() -> int:
    config = load_config()
    api_token = os.environ.get("APIFY_API_TOKEN", "").strip()
    if not api_token:
        print("ERROR: APIFY_API_TOKEN is not set.", file=sys.stderr)
        return 2

    try:
        deals = scan(api_token, config)
    except requests.HTTPError as exc:
        body = exc.response.text[:1000] if exc.response is not None else ""
        print(f"ERROR: Apify request failed: {exc}\n{body}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    write_json(deals, config)
    render_html(deals, config)
    print(f"Found {len(deals)} qualifying 90%+ Amazon deals via Apify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
