from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "deals.json"
HISTORY_PATH = ROOT / "data" / "history.json"
HTML_PATH = ROOT / "docs" / "index.html"

APIFY_BASE_URL = "https://api.apify.com/v2/acts"


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
    image_url: str | None = None


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def to_float(value):
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        value = (
            value.strip()
            .replace("$", "")
            .replace(",", "")
            .replace("%", "")
        )

        try:
            return float(value)
        except ValueError:
            return None

    return None


def first_present(raw, *keys):
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def get_tier(discount, current, reference, config):

    near_free = (
        current <= config.get("near_free_max_price", 5)
        and reference >= config.get("near_free_min_reference_price", 20)
    )

    if near_free and discount >= 80:
        return "🚨 NEAR FREE / POSSIBLE PRICING ERROR"

    if discount >= 95:
        return "🚨 POSSIBLE PRICING ERROR"

    if discount >= 90:
        return "🔥 90%+ EXTREME DEAL"

    if discount >= 80:
        return "⚡ 80%+ HUGE DEAL"

    if discount >= 70:
        return "💰 70%+ VERY STRONG DEAL"

    if discount >= 60:
        return "💰 60%+ STRONG DEAL"

    if discount >= 50:
        return "✅ 50%+ GOOD DEAL"

    return "Amazon Deal"


def score_deal(discount, current, reference, near_free):

    score = int(round(discount))

    if near_free:
        score += 8

    if discount >= 95:
        score += 5
    elif discount >= 90:
        score += 3

    if current <= 10 and reference >= 100:
        score += 4

    return min(100, max(1, score))


def extract_deal(raw, config):

    asin = str(
        first_present(
            raw,
            "asin",
            "id",
            "productAsin",
            "productId"
        )
        or ""
    ).strip()

    if not asin:
        return None

    current = to_float(
        first_present(
            raw,
            "priceToPay",
            "dealPrice",
            "price",
            "currentPrice",
            "current_price"
        )
    )

    if current is None or current <= 0:
        return None

    reference = to_float(
        first_present(
            raw,
            "basisPrice",
            "regPrice",
            "originalPrice",
            "listPrice",
            "list_price",
            "original_price"
        )
    )

    reported_discount = to_float(
        first_present(
            raw,
            "savingsPercentageValue",
            "percentOff",
            "discountPercent",
            "discount_percentage",
            "discountPercentValue"
        )
    )

    if reference and reference > current:

        discount = (
            1 - current / reference
        ) * 100

    elif reported_discount and 0 < reported_discount < 100:

        discount = reported_discount
        reference = current / (
            1 - discount / 100
        )

    else:
        return None

    discount = round(discount, 2)
    current = round(current, 2)
    reference = round(reference, 2)

    if discount < config.get(
        "minimum_discount_percent",
        0
    ):
        return None

    savings = round(
        reference - current,
        2
    )

    near_free = (
        current <= config.get(
            "near_free_max_price",
            5
        )
        and reference >= config.get(
            "near_free_min_reference_price",
            20
        )
    )

    title = str(
        first_present(
            raw,
            "title",
            "itemName",
            "name"
        )
        or asin
    )

    amazon_url = str(
        first_present(
            raw,
            "link",
            "origDealLink",
            "url",
            "productUrl"
        )
        or f"https://www.amazon.com/dp/{asin}"
    )

    image_url = str(
        first_present(
            raw,
            "image",
            "imageLink",
            "imageUrl"
        )
        or ""
    )

    return Deal(
        asin=asin,
        title=title,
        current_price=current,
        reference_price=reference,
        discount_percent=discount,
        savings=savings,
        tier=get_tier(
            discount,
            current,
            reference,
            config
        ),
        score=score_deal(
            discount,
            current,
            reference,
            near_free
        ),
        detected_at=datetime.now(
            timezone.utc
        ).isoformat(),
        amazon_url=amazon_url,
        image_url=image_url or None
    )


def query_apify(api_token, config):

    actor = config[
        "apify_actor"
    ]

    limit = int(
        config.get(
            "max_results_per_scan",
            32
        )
    )

    url = (
        f"{APIFY_BASE_URL}/"
        f"{actor}/"
        "run-sync-get-dataset-items"
    )

    actor_input = {
        "domain": "amazon.com",
        "limit": limit
    }

    response = requests.post(
        url,
        params={
            "clean": "1",
            "format": "json",
            "maxItems": limit,
            "maxTotalChargeUsd":
                config.get(
                    "max_total_charge_usd_per_run",
                    0.07
                )
        },
        headers={
            "Authorization":
                f"Bearer {api_token}",
            "Content-Type":
                "application/json",
            "User-Agent":
                "amazon-deal-finder/3.0"
        },
        json=actor_input,
        timeout=300
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            "Unexpected Apify response"
        )

    return data


def scan(api_token, config):

    raw_items = query_apify(
        api_token,
        config
    )

    deals = []

    for raw in raw_items:

        deal = extract_deal(
            raw,
            config
        )

        if deal:
            deals.append(deal)

    unique = {}

    for deal in deals:

        old = unique.get(
            deal.asin
        )

        if (
            old is None
            or deal.discount_percent
            > old.discount_percent
        ):
            unique[
                deal.asin
            ] = deal

    deals = list(
        unique.values()
    )

    deals.sort(
        key=lambda x: (
            x.discount_percent,
            x.score,
            x.savings
        ),
        reverse=True
    )

    return deals


def update_history(deals):

    history = {}

    if HISTORY_PATH.exists():

        try:
            history = json.loads(
                HISTORY_PATH.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            history = {}

    now = datetime.now(
        timezone.utc
    ).isoformat()

    for deal in deals:

        previous = history.get(
            deal.asin,
            {}
        )

        history[
            deal.asin
        ] = {

            "title":
                deal.title,

            "first_seen":
                previous.get(
                    "first_seen",
                    now
                ),

            "last_seen":
                now,

            "times_seen":
                previous.get(
                    "times_seen",
                    0
                ) + 1,

            "latest_price":
                deal.current_price,

            "lowest_price":
                min(
                    previous.get(
                        "lowest_price",
                        deal.current_price
                    ),
                    deal.current_price
                ),

            "highest_discount":
                max(
                    previous.get(
                        "highest_discount",
                        0
                    ),
                    deal.discount_percent
                ),

            "amazon_url":
                deal.amazon_url
        }

    HISTORY_PATH.write_text(
        json.dumps(
            history,
            indent=2
        ),
        encoding="utf-8"
    )


def write_json(deals):

    DATA_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    output = {

        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "source":
            "Apify Amazon Today's Deals",

        "count":
            len(deals),

        "deals":
            [
                asdict(deal)
                for deal in deals
            ]
    }

    DATA_PATH.write_text(
        json.dumps(
            output,
            indent=2
        ),
        encoding="utf-8"
    )


def render_html(deals):

    HTML_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    cards = []

    for deal in deals:

        image = ""

        if deal.image_url:

            image = (
                f'<img src="'
                f'{html.escape(deal.image_url)}'
                f'" loading="lazy">'
            )

        cards.append(
            f"""
<article class="deal">

{image}

<div class="badge">
{html.escape(deal.tier)}
</div>

<h2>
{html.escape(deal.title)}
</h2>

<div class="prices">

<div>
<span>NOW</span>
<strong>
${deal.current_price:,.2f}
</strong>
</div>

<div>
<span>REGULAR</span>
<strong>
${deal.reference_price:,.2f}
</strong>
</div>

<div>
<span>OFF</span>
<strong>
{deal.discount_percent:.1f}%
</strong>
</div>

<div>
<span>SAVE</span>
<strong>
${deal.savings:,.2f}
</strong>
</div>

</div>

<p>
Score {deal.score}/100
</p>

<a
href="{html.escape(deal.amazon_url)}"
target="_blank"
class="button">

OPEN ON AMAZON

</a>

</article>
"""
        )

    updated = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    page = f"""
<!doctype html>

<html>

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1">

<title>
Amazon Deal Finder
</title>

<style>

body {{
background:#0b0d10;
color:white;
font-family:
system-ui,
-apple-system,
sans-serif;
margin:0;
}}

header {{
max-width:1100px;
margin:auto;
padding:30px 18px;
}}

h1 {{
font-size:42px;
margin-bottom:5px;
}}

.subtitle {{
color:#aaa;
}}

main {{
max-width:1100px;
margin:auto;
padding:10px 18px 50px;
display:grid;
grid-template-columns:
repeat(
auto-fit,
minmax(290px,1fr)
);
gap:16px;
}}

.deal {{
background:#15181d;
border:1px solid #333;
border-radius:18px;
padding:18px;
}}

.deal img {{
width:100%;
height:210px;
object-fit:contain;
background:white;
border-radius:12px;
}}

.badge {{
display:inline-block;
margin-top:12px;
padding:7px 10px;
border-radius:20px;
background:#292e36;
font-size:12px;
font-weight:bold;
}}

h2 {{
font-size:18px;
}}

.prices {{
display:grid;
grid-template-columns:
1fr 1fr;
gap:8px;
}}

.prices div {{
background:#0c0e11;
padding:12px;
border-radius:10px;
}}

.prices span {{
font-size:10px;
color:#999;
display:block;
}}

.prices strong {{
font-size:19px;
}}

.button {{
display:block;
margin-top:15px;
padding:13px;
background:white;
color:black;
text-align:center;
text-decoration:none;
font-weight:bold;
border-radius:10px;
}}

</style>

</head>

<body>

<header>

<h1>
🔥 Amazon Deal Finder
</h1>

<div class="subtitle">
Biggest discounts first.
Pricing errors and near-free deals
automatically rise to the top.
</div>

<p>
{len(deals)} deals found
<br>
Updated {updated}
</p>

</header>

<main>

{''.join(cards)}

</main>

</body>

</html>
"""

    HTML_PATH.write_text(
        page,
        encoding="utf-8"
    )


def main():

    config = load_config()

    token = os.environ.get(
        "APIFY_API_TOKEN",
        ""
    ).strip()

    if not token:

        print(
            "APIFY_API_TOKEN missing",
            file=sys.stderr
        )

        return 2

    try:

        deals = scan(
            token,
            config
        )

    except requests.HTTPError as exc:

        print(
            "Apify request failed:",
            exc,
            file=sys.stderr
        )

        if exc.response is not None:

            print(
                exc.response.text[
                    :1000
                ],
                file=sys.stderr
            )

        return 3

    write_json(
        deals
    )

    update_history(
        deals
    )

    render_html(
        deals
    )

    print(
        f"Found {len(deals)} deals."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
