import os
import re
import logging
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, UTC
from email.utils import format_datetime
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from flask import Flask, request, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

REQUEST_TIMEOUT = (3.05, 5)  # (connect_timeout, read_timeout)

# HTTP Session with Connection Pooling & Retries
session = requests.Session()
retries = Retry(
    total=1,
    backoff_factor=0.2,
    status_forcelist=[500, 502, 503, 504],
    respect_retry_after_header=False,
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
session.mount("https://", adapter)
session.mount("http://", adapter)
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0"
})

COMET_URL = os.getenv("COMET_URL", "https://comet.elfhosted.com/e30=/stream/")
if not COMET_URL.endswith("/"):
    COMET_URL += "/"
if "/stream/" not in COMET_URL:
    COMET_URL = COMET_URL.rstrip("/") + "/stream/"

PROVIDERS = {
    "torrentio": os.getenv("TORRENTIO_URL", "https://torrentio.strem.fun/stream/"),
    "peerflix": os.getenv("PEERFLIX_URL", "https://addon.peerflix.mov/stream/"),
    "comet": COMET_URL,
    "thepiratebay-plus": os.getenv("THEPIRATEBAY_PLUS_URL", "https://thepiratebay-plus.strem.fun/stream/"),
}

def get_torznab_caps(provider_name: str) -> str:
    title = f"{provider_name.capitalize()} Proxy" if provider_name != "all" else "StremioArrs Proxy"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server version="1.0" title="{title}" strapline="Stremio Addon Torznab Proxy" email="contact@example.com" url="http://127.0.0.1:5100" image="http://127.0.0.1:5100/logo.png" />
  <limits default="100" max="100" />
  <searching>
    <search available="yes" supportedParams="q" />
    <tv-search available="yes" supportedParams="q,season,ep,imdbid,tvdbid,rid" />
    <movie-search available="yes" supportedParams="q,imdbid" />
  </searching>
  <categories>
    <category id="2000" name="Movies" />
    <category id="2010" name="Movies/HD" />
    <category id="5030" name="TV/SD" />
    <category id="5040" name="TV/HD" />
    <category id="5000" name="TV" />
  </categories>
  <tags></tags>
</caps>'''


def get_streams(site: str, imdb_id: str, season: Optional[str] = None, episode: Optional[str] = None, content_type: str = "movie") -> List[Dict[str, Any]]:
    base_url = PROVIDERS.get(site)
    if not base_url:
        logger.error(f"❌ Unknown site: {site}")
        return []

    if content_type == "movie":
        url = f"{base_url}{content_type}/{imdb_id}.json"
    elif content_type == "series":
        if season is not None and episode is not None:
            url = f"{base_url}{content_type}/{imdb_id}:{season}:{episode}.json"
        else:
            logger.warning(f"⚠️ Season and episode are required for series streams from {site}.")
            return []
    else:
        logger.error(f"❌ Unknown content_type for {site}: {content_type}")
        return []

    logger.info(f"🔍 Fetching streams from: {url}")

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"📦 Streams fetched successfully from {site}")
        if isinstance(data, dict):
            raw_streams = data.get("streams", [])
            if isinstance(raw_streams, list):
                return [s for s in raw_streams if isinstance(s, dict) and s.get("infoHash")]
            return []
        else:
            logger.warning(f"⚠️ Warning: Expected dict from {site} but got {type(data)}")
            return []
    except requests.RequestException as e:
        logger.error(f"❌ Network error fetching from {site}: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Unexpected error fetching from {site}: {e}")
        return []


def deduplicate_streams(streams: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicates streams by infoHash, keeping the entry with the highest seeder count."""
    best_streams: Dict[str, tuple[int, Dict[str, Any]]] = {}

    for stream in streams:
        info_hash = stream.get("infoHash")
        if not info_hash:
            continue

        norm_hash = info_hash.lower()
        title = stream.get("title") or ""
        peer_match = re.search(r'👤\s*(\d+)', title)
        seeders = int(peer_match.group(1)) if peer_match else 0

        if norm_hash not in best_streams or seeders > best_streams[norm_hash][0]:
            best_streams[norm_hash] = (seeders, stream)

    return [item[1] for item in best_streams.values()]


def fetch_all_streams(sites: List[str], imdb_id: str, season: Optional[str] = None, episode: Optional[str] = None, content_type: str = "movie") -> List[Dict[str, Any]]:
    """Fetches streams from multiple providers concurrently using ThreadPoolExecutor."""
    all_streams: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=len(sites)) as executor:
        future_to_site = {
            executor.submit(get_streams, site, imdb_id, season=season, episode=episode, content_type=content_type): site
            for site in sites
        }
        try:
            for future in as_completed(future_to_site, timeout=12):
                site = future_to_site[future]
                try:
                    streams = future.result()
                    all_streams.extend(streams)
                except Exception as e:
                    logger.error(f"❌ Unexpected error retrieving streams for {site}: {e}")
        except TimeoutError:
            logger.warning("⚠️ Overall provider fetch timed out; returning collected streams.")

    return deduplicate_streams(all_streams)


def build_rss_response(items: List[Dict[str, Any]], category_id: str = "2000", imdb_id: Optional[str] = None) -> bytes:
    rss = ET.Element("rss", version="2.0", attrib={
        "xmlns:torznab": "http://torznab.com/schemas/2015/feed"
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Torrentio results"

    for item in items:
        title = item.get("title") or "Torrent"
        infohash = item.get("infoHash")
        raw_size = item.get("size") or "0"

        if not infohash:
            continue

        # 🔍 Extract size and peers from title
        size_match = re.search(r'💾\s*([\d.]+)\s*(GB|MB)', title)
        peer_match = re.search(r'👤\s*(\d+)', title)

        # 🧮 Convert size to bytes
        if size_match:
            size_value = float(size_match.group(1))
            size_unit = size_match.group(2)
            if size_unit == "GB":
                size_bytes = int(size_value * 1024 * 1024 * 1024)
            elif size_unit == "MB":
                size_bytes = int(size_value * 1024 * 1024)
            else:
                size_bytes = 0
        else:
            try:
                size_bytes = int(raw_size)
            except (ValueError, TypeError):
                size_bytes = 0

        seeders = peer_match.group(1) if peer_match else "0"

        el = ET.SubElement(channel, "item")
        ET.SubElement(el, "title").text = title
        guid = ET.SubElement(el, "guid")
        guid.text = f"magnet:?xt=urn:btih:{infohash}"
        guid.set("isPermaLink", "false")
        ET.SubElement(el, "link").text = f"magnet:?xt=urn:btih:{infohash}"
        ET.SubElement(el, "pubDate").text = format_datetime(datetime.now(UTC))
        ET.SubElement(el, "size").text = str(size_bytes)
        ET.SubElement(el, "category").text = category_id

        enclosure = ET.SubElement(el, "enclosure")
        enclosure.set("url", f"magnet:?xt=urn:btih:{infohash}")
        enclosure.set("length", str(size_bytes))
        enclosure.set("type", "application/x-bittorrent")

        ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="infohash", value=infohash)
        ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="seeders", value=seeders)
        ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="category", value=category_id)
        ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="downloadvolumefactor", value="0")
        ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="uploadvolumefactor", value="1")

        if imdb_id:
            ET.SubElement(el, "{http://torznab.com/schemas/2015/feed}attr", name="imdbid", value=imdb_id)

    return ET.tostring(rss, encoding="utf-8", method="xml")


@app.route("/", strict_slashes=False)
def root_route() -> Response:
    return torznab_api()


@app.route("/api", defaults={"provider": None, "subpath": None}, strict_slashes=False)
@app.route("/api/<path:subpath>", defaults={"provider": None}, strict_slashes=False)
@app.route("/all", defaults={"provider": "all", "subpath": None}, strict_slashes=False)
@app.route("/all/<path:subpath>", defaults={"provider": "all"}, strict_slashes=False)
@app.route("/<provider>", defaults={"subpath": None}, strict_slashes=False)
@app.route("/<provider>/<path:subpath>", strict_slashes=False)
def torznab_api(provider: Optional[str] = None, subpath: Optional[str] = None) -> Response:
    if not provider or provider.lower() in ["api", "all"]:
        provider = "all"
    else:
        provider = provider.lower()

    if provider != "all" and provider not in PROVIDERS:
        return Response("<error>Unknown provider</error>", status=404, mimetype="application/xml")

    if subpath:
        subpath_segments = [s.strip() for s in subpath.split("/") if s.strip()]
        if any(s.lower() != "api" for s in subpath_segments):
            return Response("<error>Invalid endpoint</error>", status=404, mimetype="application/xml")

    target_sites = [provider] if provider != "all" else list(PROVIDERS.keys())

    args = request.args
    t = args.get("t")
    if not t or t == "caps":
        t = "capabilities"

    logger.info(f"------------------------------------------------------\n📥 Request received [{provider}] (subpath={subpath}): {args}")

    if t == "capabilities":
        logger.info(f"✅ TORZNAB_CAPS requested for {provider}")
        return Response(get_torznab_caps(provider), mimetype="application/xml")

    elif t in ["search", "movie-search", "movie"]:
        query = (args.get("q") or "").strip()
        imdb_id = (args.get("id") or args.get("imdbid") or "").strip()
        imdb_id = "tt" + imdb_id if imdb_id and not imdb_id.startswith("tt") else (imdb_id or None)
        cat = args.get("cat", "2000").split(",")[0]

        is_test_query = (not imdb_id) and (not query)

        if is_test_query:
            logger.info(f"🧪 Test/Empty query detected [{provider}]. Returning fallback results for Prowlarr/Arr validation.")
            if cat.startswith("5"):
                fallback_imdb = "tt0903747"  # Breaking Bad
                streams = fetch_all_streams(target_sites, fallback_imdb, season="1", episode="1", content_type="series")
                if not streams:
                    streams = [{
                        "title": "Breaking Bad S01E01 1080p BluRay 💾 1.2 GB 👤 50",
                        "infoHash": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                    }]
            else:
                fallback_imdb = "tt0133093"  # The Matrix
                streams = fetch_all_streams(target_sites, fallback_imdb, content_type="movie")
                if not streams:
                    streams = [{
                        "title": "The Matrix (1999) 1080p BluRay 💾 2.1 GB 👤 100",
                        "infoHash": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                    }]
            xml = build_rss_response(streams, category_id=cat, imdb_id=fallback_imdb)
            return Response(xml, mimetype="application/rss+xml")

        if not imdb_id and query:
            match = re.match(r"^(.*?)(?:\s+(\d{4}))?$", query)
            if match:
                title = match.group(1).strip()
                year = match.group(2) if match.group(2) else ""
            else:
                title = query
                year = ""

            try:
                omdb_url = "http://www.omdbapi.com/"
                params = {"apikey": OMDB_API_KEY, "t": title, "type": "movie"}
                if year:
                    params["y"] = year

                r = session.get(omdb_url, params=params, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                data = r.json()
                imdb_id = data.get("imdbID")
                if not imdb_id:
                    raise Exception("IMDB ID not found from OMDb")
                logger.info(f"🎬 Found imdbID via OMDb: {imdb_id}")
            except Exception as e:
                logger.error(f"❌ OMDb lookup failed: {e}  query -> {query}")
                imdb_id = None

        if imdb_id:
            all_streams = fetch_all_streams(target_sites, imdb_id, content_type="movie")
            xml = build_rss_response(all_streams, category_id=cat, imdb_id=imdb_id)
            return Response(xml, mimetype="application/rss+xml")
        else:
            logger.info("⚠️ No imdbid available, returning empty results.")
            xml = build_rss_response([], category_id=cat, imdb_id="")
            return Response(xml, mimetype="application/rss+xml")

    elif t == "tvsearch":
        query = (args.get("q") or "").strip()
        season = args.get("season", "1")
        episode = args.get("ep", "1")
        cat = args.get("cat", "5000").split(",")[0]
        imdb_id = (args.get("id") or args.get("imdbid") or "").strip()
        imdb_id = "tt" + imdb_id if imdb_id and not imdb_id.startswith("tt") else (imdb_id or None)

        is_test_query = (not imdb_id) and (not query)

        if is_test_query:
            logger.info(f"🧪 Test/Empty TV query detected [{provider}]. Returning fallback results for Prowlarr/Arr validation.")
            fallback_imdb = "tt0903747"  # Breaking Bad
            streams = fetch_all_streams(target_sites, fallback_imdb, season=season, episode=episode, content_type="series")
            if not streams:
                streams = [{
                    "title": "Breaking Bad S01E01 1080p BluRay 💾 1.2 GB 👤 50",
                    "infoHash": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
                }]
            xml = build_rss_response(streams, category_id=cat, imdb_id=fallback_imdb)
            return Response(xml, mimetype="application/rss+xml")

        logger.info(f"📺 TV Search: q={query} imdb_id={imdb_id}, season={season}, episode={episode}")

        if not imdb_id and query:
            try:
                omdb_url = "http://www.omdbapi.com/"
                params = {"apikey": OMDB_API_KEY, "t": query, "type": "series"}
                r = session.get(omdb_url, params=params, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                data = r.json()
                imdb_id = data.get("imdbID")
                if imdb_id:
                    logger.info(f"🎬 Found series imdbID via OMDb: {imdb_id}")
                else:
                    logger.warning(f"⚠️ Series IMDB ID not found from OMDb for query: {query}")
            except Exception as e:
                logger.error(f"❌ OMDb series lookup failed: {e} query -> {query}")
                imdb_id = None

        if imdb_id:
            all_streams = fetch_all_streams(target_sites, imdb_id, season=season, episode=episode, content_type="series")
            xml = build_rss_response(all_streams, category_id=cat, imdb_id=imdb_id)
            return Response(xml, mimetype="application/rss+xml")
        else:
            logger.info("⚠️ No imdbid found or provided, returning empty results.")
            xml = build_rss_response([], category_id=cat, imdb_id="")
            return Response(xml, mimetype="application/rss+xml")

    else:
        return Response("<error>Invalid t param</error>", status=400, mimetype="application/xml")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5100)
