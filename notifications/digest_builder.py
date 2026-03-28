"""Daily digest builder for property notification summaries."""

import logging

from notifications.ntfy_sender import NtfySender

logger = logging.getLogger(__name__)


class DigestBuilder:
    """Build and send daily digest of new property listings."""

    def __init__(self, ntfy_sender: NtfySender):
        self.ntfy = ntfy_sender

    def send_daily_digest(self, properties: list[dict]) -> bool:
        """Send a daily digest notification summarizing new properties.

        Returns True if sent successfully.
        """
        if not properties:
            return self.ntfy.send_alert(
                "London House Finder",
                "No new properties matching your criteria today.",
                priority="low",
            )

        text = self.build_digest_text(properties)
        return self.ntfy.send_alert(
            f"Daily Digest - {len(properties)} new listings",
            text,
            priority="default",
        )

    def build_digest_text(self, properties: list[dict]) -> str:
        """Format properties into readable digest text."""
        lines = []

        # Group by nearest station
        by_station: dict[str, list[dict]] = {}
        for p in properties:
            station = p.get("nearest_station") or "Unknown area"
            by_station.setdefault(station, []).append(p)

        # Sort stations alphabetically
        for station in sorted(by_station):
            props = sorted(by_station[station], key=lambda x: x.get("price", 0))
            lines.append(f"Near {station} ({len(props)})")

            for p in props[:5]:
                price = p.get("price", 0)
                beds = p.get("bedrooms", "?")
                sqm = p.get("sqm", 0)
                epc = p.get("epc_rating", "")
                walk = p.get("walk_minutes", 0)

                detail_parts = [f"\u00a3{price:,}", f"{beds}bed"]
                if sqm and sqm > 0:
                    detail_parts.append(f"{sqm:.0f}m\u00b2")
                if epc:
                    detail_parts.append(f"EPC {epc}")
                if walk and walk > 0:
                    detail_parts.append(f"{walk:.0f}min walk")

                lines.append(f"  {' | '.join(detail_parts)}")
                url = p.get("url", "")
                if url:
                    lines.append(f"  {url}")

            if len(props) > 5:
                lines.append(f"  ...and {len(props) - 5} more")
            lines.append("")

        # Stats
        prices = [p["price"] for p in properties if p.get("price", 0) > 0]
        if prices:
            avg = sum(prices) // len(prices)
            lines.append("Stats:")
            lines.append(f"  Avg price: \u00a3{avg:,}")
            lines.append(f"  Range: \u00a3{min(prices):,} - \u00a3{max(prices):,}")

            sqm_props = [p for p in properties if p.get("sqm", 0) > 0]
            if sqm_props:
                avg_sqm = sum(p["sqm"] for p in sqm_props) / len(sqm_props)
                lines.append(f"  Avg size: {avg_sqm:.0f}m\u00b2")
                lines.append(f"  With sqm data: {len(sqm_props)}/{len(properties)}")

        return "\n".join(lines)
