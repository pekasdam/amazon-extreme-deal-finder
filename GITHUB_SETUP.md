# GitHub Setup

Repository name: `amazon-extreme-deal-finder`

1. Create a GitHub repository named `amazon-extreme-deal-finder`.
2. Grant the ChatGPT GitHub app access to that repository.
3. Add repository secret `KEEPA_API_KEY` under **Settings → Secrets and variables → Actions**.
4. Run **Actions → Scan Amazon Extreme Deals → Run workflow** once.
5. Enable GitHub Pages from the `main` branch `/docs` folder if you want the mobile webpage.

The workflow then scans automatically every hour at minute 17 and commits updated `data/deals.json` and `docs/index.html` when results change.
