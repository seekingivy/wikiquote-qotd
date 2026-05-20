#!/usr/bin/env python3
"""
Wikiquote Quote of the Day → RSS Feed Generator
Fetches today's QOTD from Wikiquote and appends it to a local RSS XML file.
Run daily via cron. Drop feed.xml anywhere your existing web server can serve it.
"""

import os
import re
import sys
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET
import html

# ── Configuration ────────────────────────────────────────────────────────────
RSS_FILE   = Path(os.environ.get("QOTD_RSS_FILE", "./feed.xml"))
MAX_ITEMS  = int(os.environ.get("QOTD_MAX_ITEMS", "90"))   # keep ~3 months
FEED_TITLE = "Wikiquote: Quote of the Day"
FEED_LINK  = "https://en.wikiquote.org/wiki/Wikiquote:Quote_of_the_day"
FEED_DESC  = "Daily inspirational quotes from Wikiquote"
USER_AGENT = "WikiquoteQOTD-RSS/1.0 (self-hosted; +https://en.wikiquote.org/)"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Fetch QOTD from Wikiquote ─────────────────────────────────────────────────

def _wikimedia_request(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_qotd() -> tuple[str, str, str, str]:
    """
    Return (quote_text, author, author_url, page_url) for today's QOTD.
    Tries the dated sub-page first, falls back to the main QOTD page.
    """
    today = datetime.now(timezone.utc)
    date_str = today.strftime("%B %-d, %Y")          # e.g. "May 19, 2026"
    page_date = date_str.replace(" ", "_")            # "May_19,_2026"
    dated_page = f"Wikiquote:Quote_of_the_day/{page_date}"

    for page in (dated_page, "Wikiquote:Quote_of_the_day"):
        try:
            quote, author, author_url, src_url = _parse_qotd_page(page)
            if quote:
                return quote, author, author_url, src_url
        except Exception as exc:
            log.warning("Failed to parse page '%s': %s", page, exc)

    raise RuntimeError("Could not retrieve QOTD from any source")


def _parse_qotd_page(page: str) -> tuple[str, str, str, str]:
    encoded = urllib.parse.quote(page, safe=":/")
    api_url = (
        "https://en.wikiquote.org/w/api.php"
        f"?action=parse&page={encoded}&prop=wikitext&format=json"
    )
    data = _wikimedia_request(api_url)

    if "error" in data:
        raise ValueError(data["error"].get("info", "Unknown API error"))

    wikitext = data.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        return "", "", "", ""

    quote, author, author_wiki_target = _extract_from_wikitext(wikitext)

    page_url = (
        "https://en.wikiquote.org/wiki/"
        + urllib.parse.quote(page, safe=":/")
    )
    # Build the author's Wikiquote URL from the wikilink target (e.g. "Oscar Wilde")
    if author_wiki_target:
        author_url = (
            "https://en.wikiquote.org/wiki/"
            + urllib.parse.quote(author_wiki_target.replace(" ", "_"), safe=":/")
        )
    else:
        # Fall back: search URL so there's always something clickable
        author_url = (
            "https://en.wikiquote.org/w/index.php?search="
            + urllib.parse.quote(author)
        )

    return quote, author, author_url, page_url


def _extract_from_wikitext(wikitext: str) -> tuple[str, str, str]:
    """
    Parse quote, display author name, and raw wikilink target from wikitext.
    Returns (quote, author_display, author_wiki_target).
    """
    # Remove ref tags and HTML comments
    text = re.sub(r"<ref[^>]*?>.*?</ref>", "", wikitext, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # Primary pattern: | QUOTE ~ [[WikiTarget|Display]] or [[WikiTarget]]
    pattern = r"\|\s*(.*?)\s*~\s*\[\[([^\]|]+)(?:\|([^\]]*))?\]\]"
    match = re.search(pattern, text, re.DOTALL)

    if match:
        raw_quote  = match.group(1).strip()
        wiki_target = match.group(2).strip()           # raw link target for URL
        display     = (match.group(3) or wiki_target).strip()  # display name
        quote   = _clean_wikitext(raw_quote)
        author  = _clean_wikitext(display)
        return quote, author, wiki_target

    # Secondary pattern: no wiki link
    pattern2 = r"\|\s*(.*?)\s*~\s*([A-Z][^\n|{}<\[]+)"
    match = re.search(pattern2, text, re.DOTALL)
    if match:
        quote  = _clean_wikitext(match.group(1).strip())
        author = _clean_wikitext(match.group(2).strip())
        return quote, author, ""

    return "", "", ""


def _clean_wikitext(text: str) -> str:
    """Strip wikitext markup and normalize whitespace."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"'{2,3}", "", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── RSS helpers ───────────────────────────────────────────────────────────────

def _today_guid() -> str:
    return datetime.now(timezone.utc).strftime("wikiquote-qotd-%Y-%m-%d")


def _today_already_in_feed(root: ET.Element) -> bool:
    guid_today = _today_guid()
    channel = root.find("channel")
    if channel is None:
        return False
    for item in channel.findall("item"):
        guid_el = item.find("guid")
        if guid_el is not None and guid_el.text == guid_today:
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
            tree = ET.parse(RSS_FILE)
            return tree.getroot()
        except ET.ParseError as exc:
            log.warning("Existing feed is malformed (%s); starting fresh.", exc)
    return _build_new_feed()


def _add_item(
    root: ET.Element,
    quote: str,
    author: str,
    author_url: str,
    src_url: str,
) -> None:
    channel = root.find("channel")
    now = datetime.now(timezone.utc)
    pub_date  = format_datetime(now)
    date_slug = now.strftime("%Y-%m-%d")

    title = f"Wikiquote - Quote Of The Day {date_slug}"

    description = (
        f'<p style="font-size:1.1em;font-style:italic;">'
        f"&#8220;{html.escape(quote)}&#8221;"
        f"</p>"
        f'<p>&#8212; <a href="{html.escape(author_url)}">'
        f"<strong>{html.escape(author)}</strong></a></p>"
        f'<p><a href="{html.escape(src_url)}">View on Wikiquote</a></p>'
    )

    item = ET.Element("item")
    ET.SubElement(item, "title").text       = title
    ET.SubElement(item, "link").text        = author_url   # clicking the item → author page
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text     = pub_date
    ET.SubElement(item, "guid").text        = _today_guid()
    ET.SubElement(item, "author").text      = author

    # Insert newest first
    first_item = channel.find("item")
    if first_item is not None:
        channel.insert(list(channel).index(first_item), item)
    else:
        channel.append(item)

    # Prune old items beyond MAX_ITEMS
    items = channel.findall("item")
    for old_item in items[MAX_ITEMS:]:
        channel.remove(old_item)


def _save_feed(root: ET.Element) -> None:
    ET.indent(root, space="  ")
    RSS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(RSS_FILE, encoding="utf-8", xml_declaration=True)
    log.info("Feed written → %s", RSS_FILE.resolve())


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    log.info("Fetching Wikiquote QOTD…")

    root = _load_or_create_feed()

    if _today_already_in_feed(root):
        log.info("Today's quote already in feed — nothing to do.")
        return 0

    try:
        quote, author, author_url, src_url = fetch_qotd()
    except Exception as exc:
        log.error("Failed to fetch QOTD: %s", exc)
        return 1

    if not quote:
        log.error("QOTD was empty — skipping.")
        return 1

    log.info("Quote  : %s…", quote[:70])
    log.info("Author : %s", author)
    log.info("URL    : %s", author_url)

    _add_item(root, quote, author, author_url, src_url)
    _save_feed(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
