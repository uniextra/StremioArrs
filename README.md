# StremioArrs

![GitHub Release](https://img.shields.io/github/v/release/uniextra/StremioArrs?include_prereleases)
![Docker Pulls](https://img.shields.io/docker/pulls/uniextra/stremioarrs)
![License](https://img.shields.io/badge/License-MIT-blue.svg)

**StremioArrs** is a lightweight Torznab proxy that bridges the gap between popular Stremio Addons and the *Arr ecosystem (Radarr, Sonarr).

By running this proxy, you can use Stremio's vast ecosystem of torrent streaming add-ons as standard indexers in your automation setups.

## ✨ Features

- **Torznab Compliant**: Perfectly integrates as a Torznab indexer in Radarr and Sonarr.
- **Multi-Addon Support**: Automatically aggregates streams from:
  - 🍿 Torrentio
  - 🎥 Peerflix
  - ☄️ Comet
  - 🏴‍☠️ The Pirate Bay Plus (TPB+)
- **Dynamic Custom Addons**: Easily connect additional Stremio addons at runtime via `CUSTOM_ADDONS`.
- **In-Memory Caching (`cachetools`)**:
  - 24-hour TTL cache for OMDb lookups to conserve API quota.
  - 15-minute TTL cache for provider streams to speed up indexer queries.
- **Smart Parsing & Title Prepending**:
  - Automatically prepends official movie/series titles to addon streams (e.g., `Inception (2010) - [RD+] 1080p - 2GB`) to ensure Radarr/Sonarr parses quality without rejecting vague titles.
  - Accurately parses sizes (`💾`) and seeders (`👤`) into standard Torznab attributes.
- **Web Dashboard**: Built-in sleek HTML status dashboard at `http://<server-ip>:5100/` tracking uptime, requests, cache hit ratio, provider response latency, and health.
- **Independent & Aggregated Indexing**: Supports path-based routing, allowing you to configure each addon as an independent Torznab indexer (e.g., `/torrentio/api`) or aggregate them all into a single endpoint (`/api`).

## 🚀 Getting Started

### 1. Obtain an OMDb API Key
You will need a free OMDb API Key to resolve titles into IMDb IDs.
Get one here: [http://www.omdbapi.com/apikey.aspx](http://www.omdbapi.com/apikey.aspx)

### 2. Run via Docker Compose (Recommended)

Create a `docker-compose.yml` file:

```yaml
services:
  stremioarrs:
    image: uniextra/stremioarrs:latest
    container_name: stremioarrs
    environment:
      - OMDB_API_KEY=your_omdb_api_key_here
      # Optional custom addons:
      # - CUSTOM_ADDONS=myaddon=https://myaddon.strem.fun/stream/,addon2=https://addon2.com/stream/
    ports:
      - "5100:5100"
    restart: unless-stopped
```

Then run:
```bash
docker-compose up -d
```

### 3. Run via Docker CLI

```bash
docker run -d \
  --name stremioarrs \
  -e OMDB_API_KEY="your_omdb_api_key_here" \
  -p 5100:5100 \
  uniextra/stremioarrs:latest
```

## 📊 Web Dashboard

Open `http://<server-ip>:5100/` in your browser to view the real-time status dashboard:
- Total requests and cache hit ratio
- Providers response latency and health status
- Live active memory cache count
- Ready-to-copy Torznab endpoint URLs

## ⚙️ Configuring Prowlarr / Radarr / Sonarr

Once the container is running, head over to Prowlarr, Radarr, or Sonarr:

1. Go to **Settings > Indexers** (or **Indexers** in Prowlarr).
2. Click `+` and select **Torznab (Custom / Generic Torznab)**.
3. Fill in the fields:
   - **Name**: StremioArrs - Aggregated (or whatever you prefer)
   - **URL**: You can aggregate all addons or configure them as independent indexers:
     - All addons (Aggregated): `http://<server-ip>:5100/api`
     - Only Torrentio: `http://<server-ip>:5100/torrentio/api`
     - Only Comet: `http://<server-ip>:5100/comet/api`
     - Only Peerflix: `http://<server-ip>:5100/peerflix/api`
     - Only ThePirateBay+: `http://<server-ip>:5100/thepiratebay-plus/api`
     - Custom Addon: `http://<server-ip>:5100/<addon_name>/api`
     
     *(Note: Prowlarr automatically appends `/api` to URLs. All variations including `/api` and double `/api/api` are seamlessly handled without 404s).*
   - **API Key**: Leave blank or put any dummy text (not required).
   - **Categories**: 
     - For Radarr: `2000, 2010` (Movies)
     - For Sonarr: `5000, 5030, 5040` (TV)
4. Click **Test** to verify the connection, then click **Save**.

## 🛠️ Local Development (Python)

If you want to run it without Docker:

```bash
# Clone the repository
git clone https://github.com/uniextra/StremioArrs.git
cd StremioArrs

# Install dependencies
pip install -r requirements.txt

# Set your OMDb API Key
export OMDB_API_KEY="your_omdb_api_key_here"

# Run tests
pytest test_main.py -v

# Run the app
python main.py
```

## 📝 License
This project is licensed under the MIT License.
