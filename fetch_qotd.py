#!/usr/bin/env python3
"""
Wikiquote Quote of the Day → RSS Feed Generator
Fetches today's QOTD via the MediaWiki API (wikitext).
No dependencies beyond Python stdlib.
"""

import os
import re
import sys
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET
import html

# ── Configuration ─────────────────────────────────────────────────────────────
RSS_FILE   = Path(os.environ.get("QOTD_RSS_FILE", "./feed.xml"))
MAX_ITEMS  = int(os.environ.get("QOTD_MAX_ITEMS", "90"))
FEED_TITLE = "Wikiquote: Quote of the Day"
FEED_LINK  = "https://en.wikiquote.org/wiki/Wikiquote:Quote_of_the_day"
FEED_DESC  = "Daily inspirational quotes from Wikiquote"
USER_AGENT = "WikiquoteQOTD-RSS/1.0 (https://github.com/seekingivy/wikiquote-qotd)"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _wikitext_to_plain(text: str) -> str:
    """Strip wikitext markup, leaving plain readable text."""
    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # [[target|label]] → label
    text = re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', text)
    # [[word]] → word
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # Remove remaining wiki markup
    text = re.sub(r"'{2,3}", '', text)
    # Collapse whitespace / <br /> tags
    text = re.sub(r'\s*<br\s*/?>\s*', ' ', text, flags=re.IGNORECASE)
    # Remove leading sentinel comment artifact (⨀)
    text = text.replace('\u2a00', '')
    return ' '.join(text.split()).strip()


def fetch_qotd() -> tuple[str, str, str, str]:
    """
    Returns (quote, author, author_url, page_url) for today.
    Fetches the per-day QOTD subpage via the MediaWiki API.
    """
    now = datetime.now(timezone.utc)
    # Page title format: "Wikiquote:Quote_of_the_day/May_18,_2026"
    page_title = now.strftime("Wikiquote:Quote_of_the_day/%B_%-d,_%Y")
    page_url   = "https://en.wikiquote.org/wiki/" + urllib.parse.quote(
        page_title.replace(" ", "_"), safe="/:,"
    )

    api_url = (
        "https://en.wikiquote.org/w/api.php"
        "?action=parse"
        "&prop=wikitext"
        "&format=json"
        "&page=" + urllib.parse.quote(page_title)
    )

    req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if "error" in data:
        raise RuntimeError(f"API error: {data['error'].get('info', data['error'])}")

    wikitext = data["parse"]["wikitext"]["*"]

    # Extract | quote = ...
    quote_match = re.search(
        r'\|\s*quote\s*=\s*(.*?)(?=\n\s*\||\n\}\})',
        wikitext,
        re.DOTALL,
    )
    if not quote_match:
        raise RuntimeError("Could not find 'quote' field in wikitext")

    # Extract | author = ...
    author_match = re.search(
        r'\|\s*author\s*=\s*(.*?)(?=\n\s*\||\n\}\})',
        wikitext,
        re.DOTALL,
    )

    quote  = _wikitext_to_plain(quote_match.group(1))
    author = _wikitext_to_plain(author_match.group(1)) if author_match else ""

    # Link author to their Wikiquote page if we have a name
    if author:
        author_url = (
            "https://en.wikiquote.org/wiki/"
            + urllib.parse.quote(author.replace(" ", "_"))
        )
    else:
        author_url = page_url

    if not quote:
        raise RuntimeError("Quote was empty after parsing wikitext")

    return quote, author, author_url, page_url


def _today_guid() -> str:
    return datetime.now(timezone.utc).strftime("wikiquote-qotd-%Y-%m-%d")


def _today_already_in_feed(root: ET.Element) -> bool:
    channel = root.find("channel")
    if channel is None:
        return False
    for item in channel.findall("item"):
        guid_el = item.find("guid")
        if guid_el is not None and guid_el.text == _today_guid():
            return True
    return False


def _build_new_feed() -> ET.Element:
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text       = FEED_TITLE
    ET.SubElement(channel, "link").text        = FEED_LINK
    ET.SubElement(channel, "description").text = FEED_DESC
    ET.SubElement(channel, "language").text    = "en"
    ET.SubElement(channel, "generator").text   = "wikiquote-qotd-rss/1.0"
    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    return rss


def _load_or_create_feed() -> ET.Element:
    if RSS_FILE.exists():
        try:
            return ET.parse(RSS_FILE).getroot()
        except ET.ParseError as exc:
            log.warning("Feed malformed (%s); starting fresh.", exc)
    return _build_new_feed()


def _add_item(root, quote, author, author_url, page_url):
    channel = root.find("channel")
    now = datetime.now(timezone.utc)
    date_slug = now.strftime("%Y-%m-%d")

    # Title format requested: "Wikiquote - Quote of the Day - YYYY-MM-DD"
    title = f"Wikiquote - Quote of the Day - {date_slug}"

    description = (
        f'<p style="font-size:1.1em;font-style:italic;">'
        f"&#8220;{html.escape(quote)}&#8221;</p>"
        f'<p>&#8212; <a href="{html.escape(author_url)}">'
        f"<strong>{html.escape(author)}</strong></a></p>"
        f'<p><a href="{html.escape(page_url)}">View on Wikiquote</a></p>'
    )

    item = ET.Element("item")
    ET.SubElement(item, "title").text       = title
    ET.SubElement(item, "link").text        = page_url
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text     = format_datetime(now)
    ET.SubElement(item, "guid").text        = _today_guid()
    ET.SubElement(item, "author").text      = author

    first_item = channel.find("item")
    if first_item is not None:
        channel.insert(list(channel).index(first_item), item)
    else:
        channel.append(item)

    for old in channel.findall("item")[MAX_ITEMS:]:
        channel.remove(old)


def _save_feed(root):
    ET.indent(root, space="  ")
    RSS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(RSS_FILE, encoding="utf-8", xml_declaration=True)
    log.info("Feed written → %s", RSS_FILE.resolve())


def main() -> int:
    log.info("Fetching Wikiquote QOTD via API…")
    root = _load_or_create_feed()

    if _today_already_in_feed(root):
        log.info("Today's quote already in feed — nothing to do.")
        return 0

    try:
        quote, author, author_url, page_url = fetch_qotd()
    except Exception as exc:
        log.error("Failed to fetch QOTD: %s", exc)
        return 1

    if not quote:
        log.error("QOTD was empty — skipping.")
        return 1

    log.info("Quote  : %.70s…", quote)
    log.info("Author : %s", author)
    log.info("URL    : %s", page_url)

    _add_item(root, quote, author, author_url, page_url)
    _save_feed(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
