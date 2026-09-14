import pytest
import xml.etree.ElementTree as ET
from main import (
    app,
    get_streams,
    build_rss_response,
    deduplicate_streams,
    clean_title_emojis,
    parse_custom_addons,
    load_custom_addons,
    get_omdb_metadata,
    PROVIDERS,
    stream_cache,
    omdb_cache,
    metrics,
    cache_lock
)

# ---------------------------------------------------------
# Unit Tests for Data Extraction (Size and Peers)
# ---------------------------------------------------------

def parse_rss_xml(xml_bytes):
    """Helper to parse the XML response into a list of dictionaries for easier assertions."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall(".//item"):
        parsed_item = {
            "title": item.find("title").text,
            "size": item.find("size").text,
            "infohash": None,
            "seeders": None
        }
        # Extract torznab attributes
        for attr in item.findall("{http://torznab.com/schemas/2015/feed}attr"):
            name = attr.get("name")
            if name == "infohash":
                parsed_item["infohash"] = attr.get("value")
            elif name == "seeders":
                parsed_item["seeders"] = attr.get("value")
        items.append(parsed_item)
    return items

def test_build_rss_response_extracts_size_gb():
    items = [{
        "title": "Movie 1080p 💾 1.5 GB 👤 45",
        "infoHash": "abc123def456",
        "size": "0"
    }]
    xml_result = build_rss_response(items)
    parsed = parse_rss_xml(xml_result)
    
    assert len(parsed) == 1
    assert parsed[0]["size"] == str(int(1.5 * 1024 * 1024 * 1024))
    assert parsed[0]["seeders"] == "45"

def test_build_rss_response_extracts_size_mb():
    items = [{
        "title": "Episode 720p 💾 500 MB 👤 12",
        "infoHash": "def456abc123",
        "size": "0"
    }]
    xml_result = build_rss_response(items)
    parsed = parse_rss_xml(xml_result)
    
    assert len(parsed) == 1
    assert parsed[0]["size"] == str(int(500 * 1024 * 1024))
    assert parsed[0]["seeders"] == "12"

def test_build_rss_response_fallback_size_when_no_icon():
    items = [{
        "title": "Unknown Format Movie",
        "infoHash": "111222333",
        "size": "1048576" # 1MB provided in raw size
    }]
    xml_result = build_rss_response(items)
    parsed = parse_rss_xml(xml_result)
    
    assert len(parsed) == 1
    assert parsed[0]["size"] == "1048576"
    assert parsed[0]["seeders"] == "0"

def test_build_rss_response_ignores_missing_infohash():
    items = [{
        "title": "Invalid Item 💾 1.5 GB",
        # missing infoHash
    }]
    xml_result = build_rss_response(items)
    parsed = parse_rss_xml(xml_result)
    assert len(parsed) == 0

def test_deduplicate_streams_keeps_higher_seeders():
    streams = [
        {"title": "Release 1080p 👤 5 💾 2 GB", "infoHash": "HASH123"},
        {"title": "Release 1080p 👤 50 💾 2 GB", "infoHash": "hash123"},
        {"title": "Another Movie 👤 10 💾 1 GB", "infoHash": "HASH456"}
    ]
    deduped = deduplicate_streams(streams)
    assert len(deduped) == 2
    # Ensure the entry for hash123 kept is the one with 50 seeders
    hash123_entry = next(s for s in deduped if s["infoHash"].lower() == "hash123")
    assert "👤 50" in hash123_entry["title"]

# ---------------------------------------------------------
# Integration Tests for Endpoints (Torrentio, Peerflix, Comet)
# ---------------------------------------------------------

@pytest.mark.parametrize("site", ["torrentio", "peerflix", "comet", "thepiratebay-plus"])
def test_get_streams_movie_integration(site):
    """
    Tests fetching streams for a known movie (The Matrix - tt0133093) from each site.
    Validates that the site is responsive and returns a list of streams.
    """
    imdb_id = "tt0133093"
    streams = get_streams(site, imdb_id, content_type="movie")
    
    # Check that we received a list (even if empty, it shouldn't crash)
    assert isinstance(streams, list), f"{site} did not return a list for movie"
    
    # If streams are found, validate their structure
    if len(streams) > 0:
        first_stream = streams[0]
        assert "infoHash" in first_stream, f"{site} stream is missing infoHash"
        assert "title" in first_stream or "name" in first_stream, f"{site} stream is missing title/name"

@pytest.mark.parametrize("site", ["torrentio", "peerflix", "comet", "thepiratebay-plus"])
def test_get_streams_series_integration(site):
    """
    Tests fetching streams for a known series (Breaking Bad S01E01 - tt0903747) from each site.
    """
    imdb_id = "tt0903747"
    streams = get_streams(site, imdb_id, season="1", episode="1", content_type="series")
    
    assert isinstance(streams, list), f"{site} did not return a list for series"
    
    if len(streams) > 0:
        first_stream = streams[0]
        assert "infoHash" in first_stream, f"{site} stream is missing infoHash"

# ---------------------------------------------------------
# Flask App Routing and Caps Tests
# ---------------------------------------------------------

def test_capabilities_dynamic_title():
    client = app.test_client()
    
    # Test specific provider routes
    for path in ["/torrentio", "/torrentio/api", "/torrentio/api/api", "/torrentio/api/"]:
        resp = client.get(f"{path}?t=caps")
        assert resp.status_code == 200, f"Failed for {path}"
        assert b'title="Torrentio Proxy"' in resp.data

    # Test fallback/all routes (note: '/' is now Web Dashboard, /api is torznab)
    for path in ["/api", "/api/api", "/all", "/all/api", "/all/api/api"]:
        resp = client.get(f"{path}?t=caps")
        assert resp.status_code == 200, f"Failed for {path}"
        assert b'title="StremioArrs Proxy"' in resp.data

def test_invalid_provider_route():
    client = app.test_client()
    resp = client.get("/fakeaddon/api?t=caps")
    assert resp.status_code == 404
    assert b'<error>Unknown provider</error>' in resp.data

def test_invalid_subpath_route():
    client = app.test_client()
    resp = client.get("/torrentio/invalidsubpath?t=caps")
    assert resp.status_code == 404
    assert b'<error>Invalid endpoint</error>' in resp.data

def test_prowlarr_test_queries_return_fallback_results():
    client = app.test_client()
    
    # Empty query movie search on /torrentio/api
    resp1 = client.get("/torrentio/api?t=search")
    assert resp1.status_code == 200
    parsed1 = parse_rss_xml(resp1.data)
    assert len(parsed1) > 0

    # Empty query movie search on /torrentio/api/api (what Prowlarr requests)
    resp2 = client.get("/torrentio/api/api?t=search")
    assert resp2.status_code == 200
    parsed2 = parse_rss_xml(resp2.data)
    assert len(parsed2) > 0

    # Empty query on /api?t=search
    resp3 = client.get("/api?t=search")
    assert resp3.status_code == 200
    parsed3 = parse_rss_xml(resp3.data)
    assert len(parsed3) > 0

    # Empty query TV search on /api?t=tvsearch
    resp4 = client.get("/api?t=tvsearch")
    assert resp4.status_code == 200
    parsed4 = parse_rss_xml(resp4.data)
    assert len(parsed4) > 0

def test_nonexistent_searches_return_empty_results():
    client = app.test_client()

    # Specific movie search that does not exist
    resp = client.get("/api?t=search&q=nonexistentmovie123456")
    assert resp.status_code == 200
    parsed = parse_rss_xml(resp.data)
    assert len(parsed) == 0

    # Specific TV search that does not exist
    resp_tv = client.get("/api?t=tvsearch&q=nonexistenttvshow123456")
    assert resp_tv.status_code == 200
    parsed_tv = parse_rss_xml(resp_tv.data)
    assert len(parsed_tv) == 0

    # Specific nonexistent IMDB ID
    resp_imdb = client.get("/api?t=search&imdbid=tt999999999")
    assert resp_imdb.status_code == 200
    parsed_imdb = parse_rss_xml(resp_imdb.data)
    assert len(parsed_imdb) == 0

# ---------------------------------------------------------
# Web Dashboard Tests
# ---------------------------------------------------------

def test_web_dashboard_html_response():
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert b"StremioArrs Dashboard" in resp.data
    assert b"Total Requests" in resp.data
    assert b"Active Providers" in resp.data
    assert b"torrentio" in resp.data
    assert b"/torrentio/api" in resp.data
    assert b"movie/tt0133093.json" in resp.data

# ---------------------------------------------------------
# Dynamic Addons Tests
# ---------------------------------------------------------

def test_parse_custom_addons_various_formats():
    raw_str = "addon1=https://addon1.com/stream/,addon2=http://addon2.com,addon3=http://addon3.org/stream"
    parsed = parse_custom_addons(raw_str)
    assert "addon1" in parsed
    assert parsed["addon1"] == "https://addon1.com/stream/"
    assert "addon2" in parsed
    assert parsed["addon2"] == "http://addon2.com/stream/"
    assert "addon3" in parsed
    assert parsed["addon3"] == "http://addon3.org/stream/"

def test_load_custom_addons_integration():
    custom_str = "dynatest=https://dynatest.strem.fun/stream/"
    loaded = load_custom_addons(custom_str)
    assert "dynatest" in loaded
    assert "dynatest" in PROVIDERS
    assert metrics["providers"]["dynatest"]["is_custom"] is True

    # Test caps endpoint for the newly added dynamic provider
    client = app.test_client()
    resp = client.get("/dynatest/api?t=caps")
    assert resp.status_code == 200
    assert b'title="Dynatest Proxy"' in resp.data

# ---------------------------------------------------------
# In-Memory Caching Tests
# ---------------------------------------------------------

def test_stream_cache_hit():
    key = ("torrentio", "tt_cache_test", None, None, "movie")
    cached_data = [{"title": "Cached Movie 1080p 💾 2.0 GB 👤 50", "infoHash": "abcdef1234567890"}]
    
    with cache_lock:
        stream_cache[key] = cached_data
        initial_hits = metrics["cache_hits"]

    # Request streams for the same key
    streams = get_streams("torrentio", "tt_cache_test", content_type="movie")
    assert len(streams) == 1
    assert streams[0]["infoHash"] == "abcdef1234567890"
    assert metrics["cache_hits"] == initial_hits + 1

def test_omdb_cache_hit():
    cache_key = "imdb:tt8888888"
    mock_omdb_data = {
        "Title": "Cached Inception",
        "Year": "2010",
        "imdbID": "tt8888888",
        "Response": "True"
    }

    with cache_lock:
        omdb_cache[cache_key] = mock_omdb_data
        initial_hits = metrics["cache_hits"]

    res = get_omdb_metadata(imdb_id="tt8888888")
    assert res is not None
    assert res["Title"] == "Cached Inception"
    assert metrics["cache_hits"] == initial_hits + 1

# ---------------------------------------------------------
# Advanced Quality Parsing & Title Prepending Tests
# ---------------------------------------------------------

def test_clean_title_emojis():
    raw = "[RD+] 1080p BluRay 👤 45 ⚙️ Torrentio \n 💾 2.5 GB"
    cleaned = clean_title_emojis(raw)
    assert "👤" not in cleaned
    assert "⚙️" not in cleaned
    assert "💾 2.5 GB" in cleaned
    assert "\n" not in cleaned

def test_build_rss_response_prepends_media_title():
    items = [{
        "title": "[RD+] 1080p - 2GB",
        "infoHash": "aabbcc112233",
        "size": "0"
    }]
    xml_result = build_rss_response(items, media_title="Inception (2010)")
    parsed = parse_rss_xml(xml_result)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Inception (2010) - [RD+] 1080p - 2GB"

def test_build_rss_response_avoids_duplicate_prepending():
    items = [{
        "title": "Inception (2010) 1080p BluRay 💾 2.1 GB 👤 100",
        "infoHash": "ddeeff445566",
        "size": "0"
    }]
    xml_result = build_rss_response(items, media_title="Inception (2010)")
    parsed = parse_rss_xml(xml_result)
    assert len(parsed) == 1
    # Title should not duplicate the movie name
    assert not parsed[0]["title"].startswith("Inception (2010) - Inception")
    assert parsed[0]["title"] == "Inception (2010) 1080p BluRay 💾 2.1 GB"
