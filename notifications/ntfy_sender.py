"""ntfy.sh sender for push notifications."""

import logging
import os
import time

import requests


class NtfySender:
    """Send push notifications via ntfy.sh."""

    def __init__(self, config: dict):
        self.logger = logging.getLogger(self.__class__.__name__)

        ntfy_config = config.get("ntfy", {})
        self.topic = os.getenv("NTFY_TOPIC") or ntfy_config.get("topic", "")
        if not self.topic:
            self.logger.warning("No ntfy topic configured!")

        self.server = ntfy_config.get("server", "https://ntfy.sh")
        self.url = f"{self.server}/{self.topic}"
        self.priority = ntfy_config.get("priority", "high")
        self.logger.info(f"ntfy configured: {self.server}/{self.topic}")

    def send_listing(self, prop: dict, server_base_url: str = None) -> bool:
        """Send notification for a new property listing."""
        if not self.topic:
            return False

        try:
            price = prop.get("price", 0)
            bedrooms = prop.get("bedrooms", "?")
            sqm = prop.get("sqm", 0)
            station = prop.get("nearest_station", "")
            walk = prop.get("walk_minutes", 0)

            title = f"\u00a3{price:,} - {bedrooms}bed"
            if station:
                title += f" near {station}"

            lines = [
                prop.get("title", "New Property"),
                "",
                f"Address: {prop.get('address', '')}",
                f"Beds: {bedrooms} | Baths: {prop.get('bathrooms', '?')}",
                f"Price: \u00a3{price:,}",
            ]

            if sqm and sqm > 0:
                ppsqm = round(price / sqm) if price and sqm else 0
                lines.append(f"Size: {sqm:.0f}m\u00b2 (\u00a3{ppsqm:,}/m\u00b2)")

            epc = prop.get("epc_rating", "")
            if epc:
                lines.append(f"EPC: {epc}")

            if station and walk:
                lines.append(f"Walk: {walk:.0f} min to {station}")

            # Feature flags
            flags = []
            if prop.get("is_chain_free"):
                flags.append("Chain free")
            if prop.get("has_garden"):
                flags.append("Garden")
            if prop.get("has_balcony"):
                flags.append("Balcony")
            if prop.get("has_parking"):
                flags.append("Parking")
            if flags:
                lines.append(" | ".join(flags))

            lines.extend(["", f"Source: {prop.get('source', '')}", prop.get("url", "")])

            payload = {
                "topic": self.topic,
                "title": title,
                "message": "\n".join(lines),
                "priority": self._priority_to_int(self.priority),
                "tags": ["house", "uk"],
            }

            listing_url = prop.get("url", "")
            if listing_url:
                payload["click"] = listing_url
                payload["actions"] = [
                    {"action": "view", "label": "View Listing", "url": listing_url},
                ]

            response = requests.post(self.server, json=payload, timeout=10)
            if response.status_code == 200:
                self.logger.info(f"Sent notification: {prop.get('title', '')[:50]}")
                return True
            else:
                self.logger.error(f"ntfy error {response.status_code}: {response.text}")
                return False

        except requests.RequestException as e:
            self.logger.error(f"ntfy request failed: {e}")
            return False

    def send_hot_alert(self, prop: dict) -> bool:
        """Send urgent notification for a hot listing."""
        if not self.topic:
            return False

        try:
            price = prop.get("price", 0)
            bedrooms = prop.get("bedrooms", "?")
            station = prop.get("nearest_station", "")

            title = f"HOT: \u00a3{price:,} - {bedrooms}bed"
            if station:
                title += f" near {station}"

            lines = [
                "HOT LISTING!",
                "",
                prop.get("title", ""),
                f"Address: {prop.get('address', '')}",
                f"Price: \u00a3{price:,}",
            ]

            sqm = prop.get("sqm", 0)
            if sqm > 0:
                lines.append(f"Size: {sqm:.0f}m\u00b2")
            if prop.get("is_chain_free"):
                lines.append("Chain free!")
            if prop.get("has_garden"):
                lines.append("Has garden")
            if station:
                lines.append(f"{prop.get('walk_minutes', 0):.0f} min to {station}")

            lines.extend(["", prop.get("url", "")])

            payload = {
                "topic": self.topic,
                "title": title,
                "message": "\n".join(lines),
                "priority": 5,  # urgent
                "tags": ["fire", "house"],
            }

            listing_url = prop.get("url", "")
            if listing_url:
                payload["click"] = listing_url
                payload["actions"] = [
                    {"action": "view", "label": "View Listing", "url": listing_url},
                ]

            response = requests.post(self.server, json=payload, timeout=10)
            if response.status_code == 200:
                self.logger.info(f"Sent HOT alert: {prop.get('title', '')[:50]}")
                return True
            else:
                self.logger.error(f"ntfy error {response.status_code}: {response.text}")
                return False

        except requests.RequestException as e:
            self.logger.error(f"ntfy request failed: {e}")
            return False

    def send_batch(self, properties: list[dict], hot: bool = False) -> int:
        """Send multiple notifications with rate limiting."""
        if not properties:
            return 0

        success = 0
        for prop in properties:
            fn = self.send_hot_alert if hot else self.send_listing
            if fn(prop):
                success += 1
            time.sleep(1)

        self.logger.info(f"Batch sent: {success}/{len(properties)}")
        return success

    def send_alert(self, title: str, message: str, priority: str = "default") -> bool:
        """Send a plain alert message."""
        if not self.topic:
            return False
        try:
            payload = {
                "topic": self.topic,
                "title": title,
                "message": message,
                "priority": self._priority_to_int(priority),
                "tags": ["bell"],
            }
            response = requests.post(self.server, json=payload, timeout=10)
            return response.status_code == 200
        except requests.RequestException as e:
            self.logger.error(f"Failed to send alert: {e}")
            return False

    def send_stats(self, stats: dict) -> bool:
        """Send stats summary notification."""
        total = stats.get("total", {})
        lines = [
            "Last 24 hours:",
            f"  New listings: {total.get('last_24h', 0)}",
            f"  Last 7 days: {total.get('last_7d', 0)}",
            "",
            "All time:",
            f"  Total: {total.get('all_time', 0)}",
            f"  Active: {stats.get('active', 0)}",
            "",
            "By source:",
        ]
        for source, count in stats.get("by_source", {}).items():
            lines.append(f"  {source}: {count}")

        price = stats.get("price", {})
        if price.get("avg"):
            lines.extend([
                "",
                "Prices:",
                f"  Avg: \u00a3{price['avg']:,}",
                f"  Range: \u00a3{price['min']:,} - \u00a3{price['max']:,}",
            ])

        return self.send_alert("London House Finder Stats", "\n".join(lines), priority="low")

    def test(self) -> bool:
        """Send a test notification."""
        return self.send_alert(
            "London House Finder",
            "Connected! You'll receive notifications when new properties match your criteria.",
            priority="default",
        )

    def _priority_to_int(self, priority: str) -> int:
        return {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}.get(
            priority.lower(), 3
        )
