import os
import json
import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, Response
from time import mktime
from datetime import datetime, UTC
from email.utils import format_datetime
from typing import Optional, List, Dict, Any

import re
import logging

logger = logging.getLogger(__name__)

app = Flask(__name__)
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

TORZNAB_CAPS = '''<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <server version="1.0" title="Torrentio" strapline="Torrentio Proxy" email="contact@example.com" url="http://127.0.0.1:5100" image="http://127.0.0.1:5100/logo.png" />
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0"}
    streams: List[Dict[str, Any]] = []

    if site == "torrentio":
        base_url = "https://torrentio.strem.fun/stream/"
        if content_type == "movie":
            url = f"{base_url}{content_type}/{imdb_id}.json"
        elif content_type == "series":
            if season is not None and episode is not None:
                url = f"{base_url}{content_type}/{imdb_id}:{season}:{episode}.json"
            else:
                logger.warning("⚠️ Season and episode are required for series streams from Torrentio.")
                return []
        else:
            logger.error(f"❌ Unknown content_type for Torrentio: {content_type}")
            return []
    elif site == "peerflix":
        base_url = "https://addon.peerflix.mov/stream/"
        if content_type == "movie":
            url = f"{base_url}{content_type}/{imdb_id}.json"
        elif content_type == "series":
            if season is not None and episode is not None:
                url = f"{base_url}{content_type}/{imdb_id}:{season}:{episode}.json"
            else:
                logger.warning("⚠️ Season and episode are required for series streams from peerflix.")
                return []
        else:
            logger.error(f"❌ Unknown content_type for peerflix: {content_type}")
            return []        
    elif site == "comet":
        base_url = "https://comet.elfhosted.com/"
        if content_type == "movie":
            url = f"{base_url}{content_type}/{imdb_id}.json"
        elif content_type == "series":
            if season is not None and episode is not None:
                url = f"{base_url}{content_type}/{imdb_id}:{season}:{episode}.json"
            else:
                logger.warning("⚠️ Season and episode are required for series streams from Comet.")
                return []
        else:
            logger.error(f"❌ Unknown content_type for Comet: {content_type}")
            return []
    elif site == "thepiratebay-plus":
        base_url = "https://thepiratebay-plus.strem.fun/stream/"
        if content_type == "movie":
            url = f"{base_url}{content_type}/{imdb_id}.json"
        elif content_type == "series":
            if season is not None and episode is not None:
                url = f"{base_url}{content_type}/{imdb_id}:{season}:{episode}.json"
            else:
                logger.warning("⚠️ Season and episode are required for series streams from TPB Plus.")
                return []
        else:
            logger.error(f"❌ Unknown content_type for TPB Plus: {content_type}")
            return []
    else:
        logger.error(f"❌ Unknown site: {site}")
        return []

    logger.info(f"🔍 Fetching streams from: {url}")

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"📦 Streams fetched successfully from {site}")
        if isinstance(data, dict):
            streams = data.get("streams", [])
            if site == "mediafusion":
                for stream in streams:
                    if "description" in stream:
                        stream["title"] = stream.pop("description")
        else:
            logger.warning(f"⚠️ Warning: Expected dict but got {type(data)}")
            return []
    except Exception as e:
        logger.error(f"❌ Error fetching from {site}: {e}")
        return []

    return streams


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

        # 🔍 Extraer tamaño y peers del título si están
        size_match = re.search(r'💾\s*([\d.]+)\s*(GB|MB)', title)
        peer_match = re.search(r'👤\s*(\d+)', title)

        # 🧮 Convertir tamaño a bytes
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
            size_bytes = int(raw_size)

        seeders = peer_match.group(1) if peer_match else "0"

        el = ET.SubElement(channel, "item")
        ET.SubElement(el, "title").text = title
        ET.SubElement(el, "guid").text = f"magnet:?xt=urn:btih:{infohash}"
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

### TEST http://192.168.1.137:5100/api?t=movie&id=tt1375666
@app.route("/api")
def torznab_api() -> Response:
    args = request.args
    t = args.get("t")
    if t == "caps":
        t = "capabilities"

    logger.info(f"------------------------------------------------------\n\n\n📥 Request received: {args}")

    if t == "capabilities":
        logger.info(f"✅ TORZNAB_CAPS requested")
        return Response(TORZNAB_CAPS, mimetype="application/xml")

    elif t in ["search", "movie-search", "movie"]:
        imdb_id = args.get("id") or args.get("imdbid")
        imdb_id = "tt" + imdb_id if imdb_id and not imdb_id.startswith("tt") else imdb_id
        query = args.get("q")
        cat = args.get("cat", "2000").split(",")[0]

        if not imdb_id and query:
            match = re.match(r"^(.*?)(?:\s+(\d{4}))?$", query.strip())
            if match:
                title = match.group(1).strip()
                year = match.group(2) if match.group(2) else ""
            else:
                title = query.strip()
                year = ""

            try:
                omdb_url = "http://www.omdbapi.com/"
                params = {"apikey": OMDB_API_KEY, "t": title, "type": "movie"}
                if year:
                    params["y"] = year

                r = requests.get(omdb_url, params=params, timeout=10)
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
            torrentio_streams = get_streams("torrentio", imdb_id, content_type="movie")
            comet_streams = get_streams("comet", imdb_id, content_type="movie")
            peerflix_streams = get_streams("peerflix", imdb_id, content_type="movie")
            tpb_streams = get_streams("thepiratebay-plus", imdb_id, content_type="movie")
            all_streams = torrentio_streams + peerflix_streams + comet_streams + tpb_streams
            xml = build_rss_response(all_streams, category_id=cat, imdb_id=imdb_id)
            return Response(xml, mimetype="application/rss+xml")
        else:
            logger.info("⚠️ No imdbid available, returning empty results.")
            xml = build_rss_response([], category_id=cat, imdb_id="")
            return Response(xml, mimetype="application/rss+xml")

    elif t == "tvsearch":
        query = args.get("q")
        season = args.get("season", "1")
        episode = args.get("ep", "1")
        cat = args.get("cat", "5000").split(",")[0]
        imdb_id = args.get("id") or args.get("imdbid")
        imdb_id = "tt" + imdb_id if imdb_id and not imdb_id.startswith("tt") else imdb_id        
        #/api?t=tvsearch&cat=5030,5040&extended=1&offset=0&limit=100&imdbid=tt30895499&season=1&ep=8
        logger.info(f"📺 TV Search: q={query} imdb_id={imdb_id}, season={season}, episode={episode}")


        # if not imdb_id and query:
        #     try:
        #         omdb_url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={query}&type=series"
        #         r = requests.get(omdb_url)
        #         r.raise_for_status()
        #         data = r.json()
        #         imdb_id = data.get("imdbID")
        #         if not imdb_id:
        #             raise Exception("IMDB ID not found from OMDb")
        #     except Exception as e:
        #         logger.error(f"❌ OMDb error: {e}")

        if imdb_id:
            torrentio_streams = get_streams("torrentio", imdb_id, season=season, episode=episode, content_type="series")
            comet_streams = get_streams("comet", imdb_id, season=season, episode=episode, content_type="series")
            peerflix_streams = get_streams("peerflix", imdb_id, season=season, episode=episode, content_type="series")
            tpb_streams = get_streams("thepiratebay-plus", imdb_id, season=season, episode=episode, content_type="series")
            all_streams = torrentio_streams + comet_streams + peerflix_streams + tpb_streams
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
