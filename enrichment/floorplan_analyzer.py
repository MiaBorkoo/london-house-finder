"""Floor plan analyzer to extract square meters using Claude Vision and OCR."""

import base64
import io
import logging
import os
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Regex patterns for area extraction
SQM_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m(?:eters?|etres?)?|m[²2]|sqm)", re.IGNORECASE)
SQFT_PATTERN = re.compile(r"(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:sq\.?\s*f(?:ee)?t|ft[²2]|sqft)", re.IGNORECASE)
SQFT_TO_SQM = 0.0929


class FloorplanAnalyzer:
    """Extract square meters from floor plan images."""

    def __init__(self, config: dict):
        enrichment = config.get("enrichment", {})
        self.claude_model = enrichment.get("claude_model", "claude-sonnet-4-20250514")
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._api_calls = 0
        self._max_calls = enrichment.get("max_api_calls_per_run", 20)

    def extract_sqm(self, floorplan_urls: list[str]) -> tuple[float, str]:
        """Extract total sqm from floor plan images.

        Returns:
            (sqm_value, source) where source is 'floorplan_vision' or 'floorplan_ocr'.
            Returns (0.0, '') if extraction fails.
        """
        for url in floorplan_urls:
            # Try Claude Vision first (more accurate)
            if self.api_key and self._api_calls < self._max_calls:
                sqm = self._extract_with_vision(url)
                if sqm and sqm > 0:
                    return sqm, "floorplan_vision"

            # Fallback: OCR
            sqm = self._extract_with_ocr(url)
            if sqm and sqm > 0:
                return sqm, "floorplan_ocr"

        return 0.0, ""

    def _extract_with_vision(self, image_url: str) -> Optional[float]:
        """Use Claude Vision API to extract sqm from floor plan image."""
        try:
            # Download image
            image_data = self._download_image(image_url)
            if not image_data:
                return None

            # Detect media type
            media_type = "image/jpeg"
            if image_url.lower().endswith(".png"):
                media_type = "image/png"
            elif image_url.lower().endswith(".webp"):
                media_type = "image/webp"

            b64 = base64.b64encode(image_data).decode("utf-8")

            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            message = client.messages.create(
                model=self.claude_model,
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Analyze this floor plan. Find the TOTAL internal floor area "
                                "in square meters. Look for text like 'XX sq m', 'XX m²', 'XX sqm'. "
                                "If only square feet is shown, convert to square meters (divide by 10.764). "
                                "Reply with ONLY the number in square meters, or 'UNKNOWN' if not visible."
                            ),
                        },
                    ],
                }],
            )

            self._api_calls += 1
            response_text = message.content[0].text.strip()

            if response_text.upper() == "UNKNOWN":
                return None

            # Parse number from response
            match = re.search(r"(\d+(?:\.\d+)?)", response_text)
            if match:
                sqm = float(match.group(1))
                if 10 < sqm < 500:  # Sanity check
                    logger.info(f"Claude Vision extracted {sqm}m² from floor plan")
                    return sqm

            return None

        except ImportError:
            logger.warning("anthropic package not installed - skipping Vision analysis")
            return None
        except Exception as e:
            logger.debug(f"Vision extraction failed: {e}")
            return None

    def _extract_with_ocr(self, image_url: str) -> Optional[float]:
        """Use pytesseract OCR to extract sqm from floor plan image."""
        try:
            image_data = self._download_image(image_url)
            if not image_data:
                return None

            from PIL import Image, ImageFilter
            import pytesseract

            # Open and preprocess image
            img = Image.open(io.BytesIO(image_data))

            # Convert to grayscale
            img = img.convert("L")

            # Upscale small images for better OCR
            if img.width < 1000:
                factor = 1000 // img.width + 1
                img = img.resize((img.width * factor, img.height * factor), Image.LANCZOS)

            # Sharpen
            img = img.filter(ImageFilter.SHARPEN)

            # OCR
            text = pytesseract.image_to_string(img)

            # Look for sqm
            match = SQM_PATTERN.search(text)
            if match:
                sqm = float(match.group(1))
                if 10 < sqm < 500:
                    logger.info(f"OCR extracted {sqm}m² from floor plan")
                    return sqm

            # Look for sqft and convert
            match = SQFT_PATTERN.search(text)
            if match:
                sqft = float(match.group(1).replace(",", ""))
                sqm = round(sqft * SQFT_TO_SQM, 1)
                if 10 < sqm < 500:
                    logger.info(f"OCR extracted {sqft}ft² ({sqm}m²) from floor plan")
                    return sqm

            return None

        except ImportError:
            logger.warning("pytesseract/Pillow not installed - skipping OCR")
            return None
        except Exception as e:
            logger.debug(f"OCR extraction failed: {e}")
            return None

    def _download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL."""
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/122.0.0.0"
            })
            resp.raise_for_status()
            if len(resp.content) < 1000:  # Too small to be a real image
                return None
            return resp.content
        except Exception as e:
            logger.debug(f"Failed to download image {url}: {e}")
            return None
