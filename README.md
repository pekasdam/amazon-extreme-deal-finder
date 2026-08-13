# Amazon Extreme Deal Finder

A GitHub-ready scanner focused on **90%+ Amazon price drops**, including possible pricing errors and near-free items.

## What it scans

The project uses Keepa's `/deal` API rather than scraping Amazon HTML. It checks these price feeds separately:

- Amazon price (`0`)
- Marketplace New (`1`)
- Buy Box (`18`)
- Lightning Deal (`8`)
- Amazon Warehouse (`9`)

The default comparison period is Keepa's **90-day** range. Only items calculated at **90% or more below the reference price** survive the second-stage verification in Python.

## Tiers

- **NEAR FREE / POSSIBLE PRICING ERROR**: $5 or less, normally at least $20, and 95%+ down
- **POSSIBLE PRICING ERROR**: 95%+ down
- **90%+ EXTREME DROP**: 90–94.99% down

## Setup

1. Create a Keepa API account/plan and obtain an API key.
2. Create a new GitHub repository and upload this project.
3. In the GitHub repository, open **Settings → Secrets and variables → Actions**.
4. Create a repository secret named `KEEPA_API_KEY` and paste your Keepa key into it.
5. Open **Actions → Scan Amazon Extreme Deals → Run workflow** for the first scan.
6. For a webpage, enable **GitHub Pages** with the `/docs` folder on the main branch.

The included GitHub Action runs every hour at minute 17. GitHub scheduled jobs can start later than the exact minute during busy periods.

## Adjusting the rules

Edit `config.json`:

```json
{
  "minimum_discount_percent": 90,
  "pricing_error_percent": 95,
  "near_free_max_price": 5.00,
  "near_free_min_normal_price": 20.00
}
```

### Make it even more aggressive

To show only 95%+ drops, change `minimum_discount_percent` to `95`.

To define "near free" as $10 or less, change `near_free_max_price` to `10.00`.

## Important behavior

- A crossed-out Amazon MSRP is **not** used as the deal baseline.
- The scanner uses Keepa's historical/reference price math and then independently recomputes the discount from the returned current and delta values.
- The same ASIN can appear in multiple Keepa price feeds. The scanner deduplicates it and keeps the strongest version.
- A "possible pricing error" is a heuristic label, not proof that Amazon or the seller made a mistake.
- A seller or Amazon may correct a price or cancel an order before shipment.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export KEEPA_API_KEY="your_key_here"
pytest -q
python src/scanner.py
```

Generated outputs:

- `data/deals.json`
- `docs/index.html`
