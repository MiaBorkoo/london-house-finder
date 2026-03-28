# London House Finder

Property search automation for London flat purchases. Scrapes Rightmove, Zoopla, and OnTheMarket, filters by your criteria, analyzes floor plans for square meters, calculates walking distance to tube stations, and sends push notifications to your phone.

## Features

- **3 scrapers**: Rightmove, Zoopla, OnTheMarket
- **Phone-editable config** via Google Sheets (with YAML fallback)
- **Floor plan analysis** for square meters (Claude Vision + OCR)
- **Walking distance** to tube/rail stations
- **Daily digest** + instant alerts for hot listings
- **Runs automatically** via GitHub Actions

## Quick Start

1. Fork this repo
2. Install [ntfy](https://ntfy.sh) app on your phone and subscribe to a topic
3. Add GitHub secrets (see below)
4. Enable GitHub Actions

### GitHub Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `NTFY_TOPIC` | Yes | Your ntfy.sh topic name |
| `CONFIG_SHEET_ID` | No | Google Sheet ID for phone-editable config |
| `ANTHROPIC_API_KEY` | No | For floor plan sqm extraction via Claude Vision |

## Local Development

```bash
git clone <your-fork-url>
cd london-house-finder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your values
```

## CLI Commands

```bash
python main.py run              # Single scrape cycle
python main.py daemon           # Continuous mode (30 min intervals)
python main.py digest           # Send daily digest
python main.py test-ntfy        # Test push notification
python main.py config           # Show current config
python main.py stats            # Database statistics
python main.py list --hours 24  # List recent properties
python main.py cleanup --days 90  # Remove old entries
```

## Google Sheets Config

Create a public Google Sheet with 3 tabs:

**Tab: Settings** (Key-Value pairs)

| Key | Value |
|-----|-------|
| price_min | 400000 |
| price_max | 650000 |
| bedrooms_min | 2 |
| bedrooms_max | 3 |
| sqm_min | 78 |
| epc_min | C |
| must_have | balcony,garden |
| exclude_keywords | shared ownership,auction,retirement |

**Tab: Areas**

| Area Name | Postcode | Rightmove ID | Zoopla Query | OnTheMarket Outcode | Enabled |
|-----------|----------|-------------|-------------|-------------------|---------|
| Hampstead | NW3 | REGION^1187 | hampstead | NW3 | TRUE |

**Tab: Target Stations**

| Station Name | Latitude | Longitude | Max Walk Minutes |
|-------------|----------|-----------|-----------------|
| Hampstead | 51.5568 | -0.1782 | 20 |

Share the sheet as "Anyone with the link" > Viewer, and set `CONFIG_SHEET_ID` to the sheet ID from the URL.

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Estimated Costs

- **GitHub Actions**: Free (within 2000 min/month)
- **ntfy.sh**: Free
- **Claude Vision**: ~£0.01 per floor plan (~£3/month)
