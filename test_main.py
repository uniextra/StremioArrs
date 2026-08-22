import pytest
import xml.etree.ElementTree as ET
from main import get_streams, build_rss_response

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

# ---------------------------------------------------------
# Integration Tests for Endpoints (Torrentio, Peerflix, Comet)
# ---------------------------------------------------------
# Note: These tests make real HTTP requests to check if the sites are up and returning expected formats.

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
