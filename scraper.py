"""
Scrapes the free-node list published at v2cross.com.

The entry page (https://v2cross.com/en/free-v2ray-nodes/) links to a
"live" page whose URL changes over time (currently /1884.html). Rather
than hardcoding that link, we follow it from the entry page each run,
so the scraper keeps working after they rotate it.

The live page's visible node list is only partially present in the raw
HTML `requests.get()` returns -- most of it looks to be populated
client-side via JavaScript after page load, which we can't execute.
So instead of relying on the visible list, we primarily use the
"subscription URL" the page also publishes as plain text (something
like "订阅地址：https://.../pubconfig/XXXX"). That's the standard
V2Ray/Clash subscription format: a base64 blob that decodes into the
full newline-separated node list, meant to be machine-read by VPN
clients -- so it's far more reliable to scrape than the rendered page.

We still scrape the raw HTML for any inline node links too (belt and
suspenders / older layout compatibility), and merge + de-duplicate
both sources.
"""

import re
import base64
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

ENTRY_URL = "https://v2cross.com/en/free-v2ray-nodes/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

NODE_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://", "ssr://")
NODE_LINE_RE = re.compile(
    r"(?:" + "|".join(re.escape(p) for p in NODE_PREFIXES) + r")\S+"
)

# Matches the "最近测速：2026-08-01 21:48 Asia/Shanghai" style timestamp
# the page publishes next to the node snapshot, if present.
PAGE_TIMESTAMP_RE = re.compile(
    r"(?:最近测速|最近更新)[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}(?:\s+\S+)?)"
)

# Matches the "订阅地址：https://.../pubconfig/XXXX" style line the page
# publishes for importing the full node list into a VPN client.
SUBSCRIPTION_URL_RE = re.compile(r"订阅地址[:：]?\s*(https?://\S+)")


def _get_live_page_url() -> str:
    """Follow the 'Open latest node links' button from the entry page."""
    resp = requests.get(ENTRY_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    link = soup.find("a", string=re.compile("Open latest node links", re.I))
    if link and link.get("href"):
        return link["href"]

    # Fallback: any link pointing at a numeric .html page on the same domain
    for a in soup.find_all("a", href=True):
        if re.search(r"v2cross\.com/\d+\.html", a["href"]):
            return a["href"]

    # Last resort: the known current URL
    return "https://v2cross.com/1884.html"


def _extract_inline_nodes(search_text: str) -> list[str]:
    """Node links that appear as plain text directly in the page HTML."""
    nodes = NODE_LINE_RE.findall(search_text)
    return [n.strip() for n in nodes if n.strip()]


def _extract_subscription_nodes(search_text: str) -> list[str]:
    """
    Finds the page's published subscription URL, fetches it, and decodes
    the base64 blob into individual node links. Returns [] if no
    subscription URL is found or the fetch/decode fails for any reason
    (deliberately swallowed here -- this is a best-effort supplement,
    not the only source).
    """
    match = SUBSCRIPTION_URL_RE.search(search_text)
    if not match:
        return []

    sub_url = match.group(1)

    try:
        resp = requests.get(sub_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.text.strip()

        # Subscription payloads are base64 (sometimes urlsafe, sometimes
        # missing padding) -- try standard first, then urlsafe, then pad.
        decoded = None
        for candidate in (raw, raw + "=" * (-len(raw) % 4)):
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    decoded = decoder(candidate).decode("utf-8", errors="ignore")
                    break
                except Exception:
                    continue
            if decoded:
                break

        # If it wasn't base64 at all, the raw response might already be
        # a plain node list -- fall back to using it directly.
        text_to_scan = decoded if decoded else raw
        return _extract_inline_nodes(text_to_scan)

    except requests.RequestException:
        return []


def get_nodes():
    """
    Returns a dict:
        {
            "nodes": list[str]          # raw node links, deduplicated, in discovery order
            "fetched_at": str           # UTC timestamp of when we scraped, ISO-ish
            "page_timestamp": str|None  # the site's own "last updated" timestamp, if found
            "source_url": str           # the live page we pulled nodes from
        }
    Returns an empty "nodes" list (but still valid dict) if nothing could be found.
    """
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        live_url = _get_live_page_url()

        resp = requests.get(live_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Prefer <pre>/<code> blocks if present (older layout); otherwise
        # fall back to the whole page text (current layout).
        blocks = soup.find_all(["pre", "code"])
        search_text = "\n".join(b.get_text("\n") for b in blocks) or soup.get_text("\n")

        # Primary source: the published subscription URL (full list,
        # not subject to whatever JS renders on the page). Supplement
        # with any node links visible directly in the raw HTML.
        subscription_nodes = _extract_subscription_nodes(search_text)
        inline_nodes = _extract_inline_nodes(search_text)

        # de-duplicate while preserving order; subscription nodes first
        # since that's the more complete/reliable source
        seen = set()
        unique_nodes = []
        for n in subscription_nodes + inline_nodes:
            if n not in seen:
                seen.add(n)
                unique_nodes.append(n)

        page_ts_match = PAGE_TIMESTAMP_RE.search(search_text)
        page_timestamp = page_ts_match.group(1) if page_ts_match else None

        return {
            "nodes": unique_nodes,
            "fetched_at": fetched_at,
            "page_timestamp": page_timestamp,
            "source_url": live_url,
        }

    except requests.RequestException:
        return {
            "nodes": [],
            "fetched_at": fetched_at,
            "page_timestamp": None,
            "source_url": None,
        }
