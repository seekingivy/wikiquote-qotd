#!/usr/bin/env python3
"""
Wikiquote Quote of the Day → RSS Feed Generator
Scrapes today's QOTD from the Wikiquote main page HTML.
No dependencies beyond Python stdlib.
"""

import os
import re
import sys
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
import html

# ── Configuration ────────────────────────────────────────────────────────────
RSS_FILE   = Path(os.environ.get("QOTD_RSS_FILE", "./feed.xml"))
MAX_ITEMS  = int(os.environ.get("QOTD_MAX_ITEMS", "90"))
FEED_TITLE = "Wikiquote: Quote of the Day"
FEED_LINK  = "https://en.wikiquote.org/wiki/Wikiquote:Quote_of_the_day"
FEED_DESC  = "Daily inspirational quotes from Wikiquote"
# Wikimedia requires a meaningful User-Agent with contact info
USER_AGENT = "WikiquoteQOTD-RSS/1.0 (https://github.com/seekingivy/wikiquote-qotd)"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class QOTDParser(HTMLParser):
    """
    Parses the Wikiquote main page to extract the QOTD.
    The QOTD lives in a <div id="mf-qotd"> block structured like:
      <td style="..."><div>QUOTE</div></td>
      <td>~ <a href="/wiki/Author">Author</a></td>
    We find the table inside #mf-qotd and grab the first cell (quote)
    and the attribution cell (author + link).
    """

    def __init__(self):
        super().__init__()
        self.in_qotd     = False
        self.depth       = 0          # div depth inside #mf-qotd
        self.quote_parts = []
        self.author      = ""
        self.author_href = ""
        self._in_td      = 0
        self._td_count   = 0
        self._in_author_a = False
        self._capture_quote = False
        self._capture_author = False
        self._done       = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        attrs = dict(attrs)

        if tag == "div" and attrs.get("id") == "mf-qotd":
            self.in_qotd = True
            self.depth = 1
            return

        if self.in_qotd:
            if tag == "div":
                self.depth += 1

            if tag == "td":
                self._td_count += 1
                self._in_td += 1
                if self._td_count == 1:
                    self._capture_quote = True
                elif self._td_count == 2:
                    self._capture_author = True

            if self._capture_author and tag == "a":
                href = attrs.get("href", "")
                if href.startswith("/wiki/") and ":" not in href[6:]:
                    self.author_href = "https://en.wikiquote.org" + href
                    self._in_author_a = True

    def handle_endtag(self, tag):
        if self._done:
            return
        if not self.in_qotd:
            return

        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.in_qotd = False
                self._done = True

        if tag == "td":
            self._in_td -= 1
            if self._td_count == 2 and self._in_td == 0:
                self._capture_author = False
                self._done = True

        if tag == "a" and self._in_author_a:
            self._in_author_a = False

    def handle_data(self, data):
        if self._done:
            return
        if self._capture_quote and self._td_count == 1:
            self.quote_parts.append(data)
        if self._capture_author and self._td_count == 2:
            if self._in_author_a:
                self.author += data
            elif data.strip() and data.strip() not in ("~", "—", "-"):
                # plain text attribution with no link
                self.author += data

    @property
    def quote(self):
        text = " ".join("".join(self.quote_parts).split())
        # strip leading/trailing quotation marks added by CSS
        return text.strip('\u201c\u201d"\'').strip()


def fetch_qotd() -> tuple[str, str, str]:
    """Return (quote, author, author_url) from the Wikiquote main page."""
    url = "https://en.wikiquote.org/wiki/Main_Page"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")

    parser = QOTDParser()
    parser.feed(body)

    quote  = parser.quote.strip()
    author = parser.author.strip().lstrip("~— ").strip()
    author_url = parser.author_href or (
        "https://en.wikiquote.org/w/index.php?search=" +
        urllib.parse.quote(author)
    )

    if not quote:
        raise RuntimeError("Could not parse QOTD from Wikiquote main page")

    return quote, author, author_url


# ── RSS helpers ───────────────────────────────────────────────────────────────

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


def _add_item(root, quote, author, author_url):
    channel = root.find("channel")
    now = datetime.now(timezone.utc)
    date_slug = now.strftime("%Y-%m-%d")

    description = (
        f'<p style="font-size:1.1em;font-style:italic;">'
        f"&#8220;{html.escape(quote)}&#8221;</p>"
        f'<p>&#8212; <a href="{html.escape(author_url)}">'
        f"<strong>{html.escape(author)}</strong></a></p>"
        f'<p><a href="{html.escape(FEED_LINK)}">View on Wikiquote</a></p>'
    )

    item = ET.Element("item")
    ET.SubElement(item, "title").text       = f"Wikiquote - Quote Of The Day {date_slug}"
    ET.SubElement(item, "link").text        = author_url
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


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    log.info("Fetching Wikiquote QOTD from main page…")

    root = _load_or_create_feed()

    if _today_already_in_feed(root):
        log.info("Today's quote already in feed — nothing to do.")
        return 0

    try:
        quote, author, author_url = fetch_qotd()
    except Exception as exc:
        log.error("Failed to fetch QOTD: %s", exc)
        return 1

    if not quote:
        log.error("QOTD was empty — skipping.")
        return 1

    log.info("Quote  : %.70s…", quote)
    log.info("Author : %s", author)
    log.info("URL    : %s", author_url)

    _add_item(root, quote, author, author_url)
    _save_feed(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
