"""London House Finder - Main application entry point."""

import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import schedule
from dotenv import load_dotenv

from core.aggregator import PropertyAggregator
from core.database import Database
from enrichment.listing_enricher import ListingEnricher
from notifications.ntfy_sender import NtfySender
from utils.config_loader import ConfigLoader


def setup_logging(level=logging.INFO):
    """Set up logging with console and file handlers."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers = []

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console)

    fh = logging.FileHandler(logs_dir / "house_finder.log")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(fh)

    return logger


class HouseFinder:
    """Main application class for London House Finder."""

    def __init__(self):
        load_dotenv()

        # Load config (Google Sheets or YAML fallback)
        loader = ConfigLoader()
        self.config = loader.load()

        # Set up logging
        log_level = getattr(
            logging,
            self.config.get("logging", {}).get("level", "INFO").upper(),
            logging.INFO,
        )
        setup_logging(log_level)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.logger.info("=" * 50)
        self.logger.info("London House Finder starting up...")
        self.logger.info(f"Config source: {self.config.get('_source', 'unknown')}")
        self.logger.info("=" * 50)

        # Initialize components
        db_path = self.config.get("database", {}).get("path", "data/properties.db")
        self.database = Database(db_path)
        self.ntfy = NtfySender(self.config)
        self.enricher = ListingEnricher(self.config, self.database)
        self.aggregator = PropertyAggregator(self.config, self.database)

        self.running = True

    def run_once(self) -> dict:
        """Run a single scrape cycle."""
        self.logger.info("Starting scan...")
        started = datetime.now()

        new_listings, hot_listings = self.aggregator.process_new_listings()

        result = {
            "found": len(new_listings),
            "hot": len(hot_listings),
            "notified": 0,
            "hot_notified": 0,
        }

        if not new_listings and not hot_listings:
            self.logger.info("No new matching listings found")
            return result

        self.logger.info(
            f"Found {len(new_listings)} new listings, {len(hot_listings)} hot"
        )

        # Enrich with distance + floor plan data
        if new_listings:
            new_listings = self.enricher.enrich(new_listings)
            # Re-check hot status after enrichment (sqm data may change things)
            hot_listings = [p for p in new_listings if self.aggregator.property_filter.is_hot(p)]

        if self._is_quiet_hours():
            self.logger.info("Quiet hours - skipping notifications")
            return result

        # Send hot alerts first (urgent)
        for prop in hot_listings:
            prop_dict = prop.to_dict()
            if self.ntfy.send_hot_alert(prop_dict):
                self.database.mark_notified_instant(prop.id)
                result["hot_notified"] += 1
            time.sleep(1)

        # Send regular notifications for non-hot new listings
        for prop in new_listings:
            if prop not in hot_listings:
                prop_dict = prop.to_dict()
                if self.ntfy.send_listing(prop_dict):
                    self.database.mark_notified_instant(prop.id)
                    result["notified"] += 1
                time.sleep(1)

        # Log scrape run
        self.database.log_scrape_run({
            "started_at": started.isoformat(),
            "properties_found": result["found"],
            "properties_new": result["found"],
            "properties_matching": result["found"],
        })

        self.logger.info(
            f"Notifications sent: {result['notified']} regular, "
            f"{result['hot_notified']} hot alerts"
        )
        return result

    def send_digest(self) -> int:
        """Send daily digest of undigested properties."""
        properties = self.database.get_undigested_properties()
        if not properties:
            self.logger.info("No undigested properties for digest")
            return 0

        # Format digest message
        lines = [f"Daily Digest - {len(properties)} new listings", ""]

        # Group by nearest station
        by_station = {}
        for p in properties:
            station = p.get("nearest_station") or "Unknown area"
            by_station.setdefault(station, []).append(p)

        for station in sorted(by_station):
            props = sorted(by_station[station], key=lambda x: x.get("price", 0))
            lines.append(f"Near {station} ({len(props)}):")
            for p in props[:5]:
                price = p.get("price", 0)
                beds = p.get("bedrooms", "?")
                sqm = p.get("sqm", 0)
                sqm_str = f" | {sqm:.0f}m\u00b2" if sqm else ""
                epc = p.get("epc_rating", "")
                epc_str = f" | EPC {epc}" if epc else ""
                lines.append(f"  \u00a3{price:,} - {beds}bed{sqm_str}{epc_str}")
                lines.append(f"  {p.get('url', '')}")
            if len(props) > 5:
                lines.append(f"  ... and {len(props) - 5} more")
            lines.append("")

        # Stats
        prices = [p["price"] for p in properties if p.get("price", 0) > 0]
        if prices:
            lines.extend([
                "Stats:",
                f"  Avg price: \u00a3{sum(prices) // len(prices):,}",
                f"  Range: \u00a3{min(prices):,} - \u00a3{max(prices):,}",
            ])

        self.ntfy.send_alert("London House Finder", "\n".join(lines), priority="default")
        self.database.mark_digest_sent([p["id"] for p in properties])
        self.logger.info(f"Sent digest with {len(properties)} properties")
        return len(properties)

    def _is_quiet_hours(self) -> bool:
        quiet = self.config.get("schedule", {}).get("quiet_hours", {})
        if not quiet.get("enabled", False):
            return False
        try:
            now = datetime.now().time()
            start = datetime.strptime(quiet.get("start", "23:00"), "%H:%M").time()
            end = datetime.strptime(quiet.get("end", "07:00"), "%H:%M").time()
            if start > end:
                return now >= start or now <= end
            return start <= now <= end
        except Exception:
            return False

    def run_daemon(self):
        """Run continuously on schedule."""
        interval = self.config.get("schedule", {}).get("interval_minutes", 30)
        schedule.every(interval).minutes.do(self.run_once)
        schedule.every().day.at("08:00").do(self.send_digest)

        self.logger.info(f"Daemon started. Scanning every {interval} minutes.")

        # Run immediately
        self.run_once()

        while self.running:
            schedule.run_pending()
            time.sleep(1)

    def stop(self):
        self.logger.info("Shutting down...")
        self.running = False


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose):
    """London House Finder - Property search automation for London."""
    if verbose:
        setup_logging(logging.DEBUG)


@cli.command()
def run():
    """Run a single scrape cycle."""
    finder = HouseFinder()
    result = finder.run_once()
    click.echo(f"Found {result['found']} new, {result['hot']} hot, sent {result['notified'] + result['hot_notified']} notifications")


@cli.command()
def daemon():
    """Run continuously on schedule."""
    finder = HouseFinder()

    def handler(sig, frame):
        finder.stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    finder.run_daemon()


@cli.command()
def digest():
    """Send daily digest of new properties."""
    finder = HouseFinder()
    count = finder.send_digest()
    click.echo(f"Digest sent with {count} properties")


@cli.command("test-ntfy")
def test_ntfy():
    """Send a test notification."""
    load_dotenv()
    loader = ConfigLoader()
    config = loader.load()
    ntfy = NtfySender(config)
    if ntfy.test():
        click.echo("Test notification sent!")
    else:
        click.echo("Failed to send test notification", err=True)


@cli.command()
def config():
    """Show current configuration."""
    load_dotenv()
    loader = ConfigLoader()
    cfg = loader.load()
    source = cfg.get("_source", "unknown")
    click.echo(f"Config source: {source}")

    search = cfg.get("search", {})
    click.echo(f"Price: \u00a3{search.get('price_min', 0):,} - \u00a3{search.get('price_max', 0):,}")
    click.echo(f"Bedrooms: {search.get('bedrooms_min', 0)}-{search.get('bedrooms_max', 0)}")
    click.echo(f"Min sqm: {search.get('sqm_min', 0)}")
    click.echo(f"Min EPC: {search.get('epc_min', 'N/A')}")

    areas = cfg.get("areas", [])
    click.echo(f"\nAreas ({len(areas)}):")
    for area in areas:
        click.echo(f"  {area['name']} ({area.get('postcode', '')})")

    stations = cfg.get("stations", [])
    click.echo(f"\nStations ({len(stations)}):")
    for s in stations:
        click.echo(f"  {s['name']} ({s['lat']:.4f}, {s['lon']:.4f})")

    scrapers = cfg.get("scrapers", {})
    click.echo(f"\nScrapers:")
    for name, scfg in scrapers.items():
        status = "enabled" if scfg.get("enabled") else "disabled"
        click.echo(f"  {name}: {status}")


@cli.command()
def stats():
    """Show database statistics."""
    finder = HouseFinder()
    s = finder.database.get_stats()
    total = s.get("total", {})
    price = s.get("price", {})

    click.echo("\nStatistics:")
    click.echo(f"  Total properties: {total.get('all_time', 0)}")
    click.echo(f"  Last 24h: {total.get('last_24h', 0)}")
    click.echo(f"  Last 7d: {total.get('last_7d', 0)}")
    click.echo(f"  Active: {s.get('active', 0)}")
    click.echo(f"  Instant notified: {s.get('notified_instant', 0)}")
    click.echo(f"  Digested: {s.get('notified_digest', 0)}")

    if s.get("by_source"):
        click.echo("\nBy source:")
        for source, count in s["by_source"].items():
            click.echo(f"  {source}: {count}")

    if price.get("avg"):
        click.echo(f"\nPrice range: \u00a3{price['min']:,} - \u00a3{price['max']:,}")
        click.echo(f"Average: \u00a3{price['avg']:,}")


@cli.command("list")
@click.option("--hours", default=24, help="Hours to look back")
def list_properties(hours):
    """List recent properties."""
    finder = HouseFinder()
    properties = finder.database.get_recent_properties(hours)
    click.echo(f"\nProperties from last {hours} hours ({len(properties)}):\n")

    for p in properties:
        status = ""
        if p.get("notified_instant"):
            status = "[notified] "
        elif p.get("notified_digest"):
            status = "[digested] "

        price = p.get("price", 0)
        beds = p.get("bedrooms", "?")
        sqm = p.get("sqm", 0)
        sqm_str = f" | {sqm:.0f}m\u00b2" if sqm else ""
        station = p.get("nearest_station", "")
        station_str = f" | {station}" if station else ""

        click.echo(f"{status}\u00a3{price:,} - {beds}bed{sqm_str}{station_str}")
        click.echo(f"  {p.get('address', '')}")
        click.echo(f"  {p.get('url', '')}\n")


@cli.command()
@click.option("--days", default=90, help="Remove properties older than N days")
def cleanup(days):
    """Remove old properties from database."""
    finder = HouseFinder()
    count = finder.database.cleanup_old_properties(days)
    click.echo(f"Removed {count} properties older than {days} days")


if __name__ == "__main__":
    cli()
