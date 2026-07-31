"""
Scrapes the free-node list published at v2cross.com.

The entry page (https://v2cross.com/en/free-v2ray-nodes/) links to a
"live" page whose URL changes over time (currently /1884.html). Rather
than hardcoding that link, we follow it from the entry page each run,
so the scraper keeps working after they rotate it.

The live page publishes node links as plain text lines starting with
a known protocol prefix (vless://, vmess://, trojan://, ss://, ssr://)
inside a <pre>/<code> block. We match on those prefixes with a regex
instead of relying on CSS classes, since the site's markup/theme can
change but the link format is stable.
"""

import re
import requests
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
    r"^(?:" + "|".join(re.escape(p) for p in NODE_PREFIXES) + r").+", re.MULTILINE
)


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


def get_nodes():
    """
    Returns a list[str] of raw node links (vless://, vmess://, trojan://, ...).
    Returns an empty list if nothing could be found.
    """
    try:
        live_url = _get_live_page_url()

        resp = requests.get(live_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Node links live inside a <pre> or <code> block; grab those first,
        # falling back to the whole page text if the structure changes.
        blocks = soup.find_all(["pre", "code"])
        search_text = "\n".join(b.get_text("\n") for b in blocks) or soup.get_text("\n")

        nodes = NODE_LINE_RE.findall(search_text)
        # de-duplicate while preserving order
        seen = set()
        unique_nodes = []
        for n in nodes:
            n = n.strip()
            if n and n not in seen:
                seen.add(n)
                unique_nodes.append(n)

        return unique_nodes

    except requests.RequestException:
        return []

