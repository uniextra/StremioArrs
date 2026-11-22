import time
import threading
from unittest.mock import MagicMock, patch
import pytest
import requests
import xml.etree.ElementTree as ET
import main
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
# Integration Tests for Endpoints (Torrentio, Peerflix, TorrentsDB, Meteor, Hydra, TPB+)
# ---------------------------------------------------------

@pytest.mark.parametrize("site", ["torrentio", "peerflix", "torrentsdb", "meteor", "hydra", "thepiratebay-plus"])
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
        assert "title" in first_stream or "description" in first_stream or "name" in first_stream, f"{site} stream is missing title/description/name"

@pytest.mark.parametrize("site", ["torrentio", "peerflix", "torrentsdb", "meteor", "hydra", "thepiratebay-plus"])
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


def test_build_rss_response_handles_meteor_format():
    items = [{
        "name": "[P2P] Meteor 2160p",
        "description": "📄 The.Matrix.1999.2160p 📺 2160p 💾 35.09 GiB 👥 78 seeders",
        "infoHash": "11223344556677889900aabbccddeeff11223344",
        "behaviorHints": {"videoSize": 37677449216}
    }]
    xml_result = build_rss_response(items, media_title="The Matrix (1999)")
    parsed = parse_rss_xml(xml_result)
    assert len(parsed) == 1
    assert parsed[0]["seeders"] == "78"
    assert parsed[0]["size"] == str(int(35.09 * 1024 * 1024 * 1024))


def test_build_rss_response_handles_hydra_format():
    items = [{
        "title": "The Matrix (1999) 1080p ◈ 18.45 GB 👤100:60",
        "infoHash": "556677889900aabbccddeeff1122334455667788",
        "size": "0"
    }]
    xml_result = build_rss_response(items, media_title="The Matrix (1999)")
    parsed = parse_rss_xml(xml_result)
    assert len(parsed) == 1
    assert parsed[0]["seeders"] == "100"
    assert parsed[0]["size"] == str(int(18.45 * 1024 * 1024 * 1024))
    assert ":60" not in parsed[0]["title"]


def test_hydra_alias_route():
    client = app.test_client()
    resp = client.get("/hydra-torrents/api?t=caps")
    assert resp.status_code == 200
    assert "Hydra Proxy" in resp.data.decode("utf-8")


# ---------------------------------------------------------
# Performance & Resilience Tests (TDD)
# ---------------------------------------------------------

def test_fetch_all_streams_non_blocking_timeout():
    release_slow = threading.Event()

    def fake_get_streams(site, imdb_id, season=None, episode=None, content_type="movie"):
        if site == "fast":
            return [{"title": "Fast 1080p 💾 2.0 GB 👤 50", "infoHash": "fast123456"}]
        # Block until released or 3.0s elapses
        release_slow.wait(timeout=3.0)
        return [{"title": "Slow 1080p 💾 2.0 GB 👤 10", "infoHash": "slow123456"}]

    start = time.perf_counter()
    try:
        with patch.object(main, "get_streams", side_effect=fake_get_streams):
            streams = main.fetch_all_streams(["fast", "slow"], "tt0133093", timeout=0.3)
        elapsed = time.perf_counter() - start
    finally:
        release_slow.set()

    assert elapsed < 1.0, f"fetch_all_streams blocked for {elapsed:.2f}s"
    assert len(streams) == 1
    assert streams[0]["infoHash"] == "fast123456"


def test_circuit_breaker_trips_and_recovers():
    site = "torrentio"
    with cache_lock:
        stream_cache.clear()
        main.negative_stream_cache.clear()
    main.provider_cb.pop(site, None)

    try:
        threshold = main.CB_FAILURE_THRESHOLD
        with patch.object(main.session, "get", side_effect=requests.Timeout("timed out")) as mock_get:
            for i in range(threshold):
                res = get_streams(site, f"tt900000{i}", content_type="movie")
                assert res == []

            assert mock_get.call_count == threshold
            assert main.is_provider_circuit_open(site) is True
            assert metrics["providers"][site]["status"] == "cooldown"

            # Subsequent call while circuit is open must short-circuit with 0 HTTP calls
            res_open = get_streams(site, "tt9000099", content_type="movie")
            assert res_open == []
            assert mock_get.call_count == threshold

        # Simulate cooldown expiry -> probe request succeeds and closes circuit
        main.provider_cb[site]["open_until"] = time.monotonic() - 1.0
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status.return_value = None
        ok_resp.json.return_value = {
            "streams": [{"title": "Recovered 1080p 💾 2.0 GB 👤 25", "infoHash": "rec123456"}]
        }
        with patch.object(main.session, "get", return_value=ok_resp) as mock_get:
            res_rec = get_streams(site, "tt9000100", content_type="movie")
            assert len(res_rec) == 1
            assert mock_get.call_count == 1
            assert main.is_provider_circuit_open(site) is False
            assert main.provider_cb[site]["failures"] == 0
            assert metrics["providers"][site]["status"] == "online"
    finally:
        main.provider_cb.pop(site, None)
        with cache_lock:
            stream_cache.clear()
            main.negative_stream_cache.clear()


def test_negative_stream_cache_short_ttl():
    site = "peerflix"
    with cache_lock:
        stream_cache.clear()
        main.negative_stream_cache.clear()
    main.provider_cb.pop(site, None)

    try:
        # 1. Empty valid response goes to negative_stream_cache, not stream_cache
        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.raise_for_status.return_value = None
        empty_resp.json.return_value = {"streams": []}

        empty_key = (site, "tt8000001", None, None, "movie")
        with patch.object(main.session, "get", return_value=empty_resp) as mock_get:
            res1 = get_streams(site, "tt8000001", content_type="movie")
            res2 = get_streams(site, "tt8000001", content_type="movie")
            assert res1 == []
            assert res2 == []
            assert mock_get.call_count == 1
            with cache_lock:
                assert empty_key not in stream_cache
                assert empty_key in main.negative_stream_cache

        # 2. Network failure goes to negative_stream_cache (short TTL), not 15m stream_cache
        err_key = (site, "tt8000002", None, None, "movie")
        with patch.object(main.session, "get", side_effect=requests.ConnectionError("boom")) as mock_get:
            res_err1 = get_streams(site, "tt8000002", content_type="movie")
            res_err2 = get_streams(site, "tt8000002", content_type="movie")
            assert res_err1 == []
            assert res_err2 == []
            assert mock_get.call_count == 1
            with cache_lock:
                assert err_key not in stream_cache
                assert err_key in main.negative_stream_cache
    finally:
        main.provider_cb.pop(site, None)
        with cache_lock:
            stream_cache.clear()
            main.negative_stream_cache.clear()


def test_cinemeta_metadata_resolution_and_fallback(monkeypatch):
    with cache_lock:
        omdb_cache.clear()

    try:
        cinemeta_resp = MagicMock()
        cinemeta_resp.status_code = 200
        cinemeta_resp.raise_for_status.return_value = None
        cinemeta_resp.json.return_value = {
            "meta": {"name": "The Matrix", "releaseInfo": "1999"}
        }

        monkeypatch.setattr(main, "OMDB_API_KEY", None)
        with patch.object(main.session, "get", return_value=cinemeta_resp) as mock_get:
            meta = main.resolve_metadata_by_imdb("tt0133093", content_type="movie")
            assert meta is not None
            assert meta["Title"] == "The Matrix"
            assert meta["Year"] == "1999"
            assert meta["imdbID"] == "tt0133093"
            assert mock_get.call_count == 1
            assert "v3-cinemeta.strem.io/meta/movie/tt0133093.json" in mock_get.call_args[0][0]

        # Should be cached now under imdb:tt0133093
        with cache_lock:
            assert "imdb:tt0133093" in omdb_cache

        # Test fallback to OMDb when Cinemeta fails
        omdb_fallback_resp = MagicMock()
        omdb_fallback_resp.status_code = 200
        omdb_fallback_resp.raise_for_status.return_value = None
        omdb_fallback_resp.json.return_value = {
            "Title": "Inception",
            "Year": "2010",
            "imdbID": "tt1375666",
            "Response": "True",
        }
        monkeypatch.setattr(main, "OMDB_API_KEY", "test_key")

        def side_effect_fallback(url, *args, **kwargs):
            if "v3-cinemeta.strem.io" in url:
                raise requests.Timeout("cinemeta timeout")
            return omdb_fallback_resp

        with patch.object(main.session, "get", side_effect=side_effect_fallback):
            meta_fb = main.resolve_metadata_by_imdb("tt1375666", content_type="movie")
            assert meta_fb is not None
            assert meta_fb["Title"] == "Inception"
            assert meta_fb["Year"] == "2010"
    finally:
        with cache_lock:
            omdb_cache.clear()


def test_singleflight_coalescing_omdb(monkeypatch):
    with cache_lock:
        omdb_cache.clear()

    monkeypatch.setattr(main, "OMDB_API_KEY", "test_key")
    call_counter = {"count": 0}
    counter_lock = threading.Lock()

    def slow_omdb_get(url, *args, **kwargs):
        with counter_lock:
            call_counter["count"] += 1
        time.sleep(0.15)
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "Title": "Coalesced Movie",
            "Year": "2024",
            "imdbID": "tt7777777",
            "Response": "True",
        }
        return resp

    results = []
    errors = []

    def worker():
        try:
            results.append(get_omdb_metadata(imdb_id="tt7777777"))
        except Exception as exc:
            errors.append(exc)

    try:
        with patch.object(main.session, "get", side_effect=slow_omdb_get):
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        assert not errors
        assert len(results) == 5
        assert call_counter["count"] == 1
        assert all(r is not None and r["Title"] == "Coalesced Movie" for r in results)
    finally:
        with cache_lock:
            omdb_cache.clear()


def test_disabled_providers_filtering(monkeypatch):
    monkeypatch.setenv("DISABLED_PROVIDERS", "meteor, peerflix")
    disabled = main.parse_disabled_providers()
    assert disabled == {"meteor", "peerflix"}

    active = main.get_active_sites("all")
    assert "torrentio" in active
    assert "hydra" in active
    assert "meteor" not in active
    assert "peerflix" not in active

    # Direct single-provider lookup still allows explicit selection or empty check
    monkeypatch.setenv("DISABLED_PROVIDERS", "")
    active_all = main.get_active_sites("all")
    assert "meteor" in active_all
    assert "peerflix" in active_all


def test_parallel_metadata_and_streams_in_torznab_api(monkeypatch):
    with cache_lock:
        omdb_cache.clear()
        stream_cache.clear()
        main.negative_stream_cache.clear()

    def fake_resolve_meta(imdb_id, content_type="movie"):
        time.sleep(0.15)
        return {"Title": "The Matrix", "Year": "1999", "imdbID": imdb_id, "Response": "True"}

    def fake_fetch_all(sites, imdb_id, season=None, episode=None, content_type="movie", timeout=None):
        time.sleep(0.15)
        return [{
            "title": "1080p BluRay 💾 2.1 GB 👤 100",
            "infoHash": "aabbcc112233445566",
            "size": "0",
        }]

    try:
        client = app.test_client()
        start = time.perf_counter()
        with patch.object(main, "resolve_metadata_by_imdb", side_effect=fake_resolve_meta) as mock_meta, \
             patch.object(main, "fetch_all_streams", side_effect=fake_fetch_all) as mock_streams:
            resp = client.get("/api?t=movie&imdbid=tt0133093")
        elapsed = time.perf_counter() - start

        assert resp.status_code == 200
        assert mock_meta.call_count == 1
        assert mock_streams.call_count == 1
        # If run sequentially (0.15 + 0.15), elapsed >= 0.30s; in parallel, ~0.15s (< 0.28s)
        assert elapsed < 0.28, f"Expected parallel execution, took {elapsed:.3f}s"
        parsed = parse_rss_xml(resp.data)
        assert len(parsed) == 1
        assert parsed[0]["title"].startswith("The Matrix (1999) - ")
    finally:
        with cache_lock:
            omdb_cache.clear()
            stream_cache.clear()
            main.negative_stream_cache.clear()



