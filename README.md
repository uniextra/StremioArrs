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
- **Smart Parsing**: Accurately parses sizes (`💾`) and seeders (`👤`) from the addons to ensure your quality profiles and minimum seeder limits are respected.
- **OMDb API Integration**: Converts text-based fallback queries from Radarr/Sonarr directly into valid IMDb IDs needed by Stremio Addons.
- **Independent Indexing**: Supports path-based routing, allowing you to configure each addon as an independent Torznab indexer (e.g., `/torrentio/api`) or aggregate them all into a single endpoint (`/api`).

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

## ⚙️ Configuring Radarr / Sonarr

Once the container is running, head over to your Radarr or Sonarr web interface:

1. Go to **Settings > Indexers**.
2. Click the `+` button to add a new Indexer.
3. Select **Torznab** (Custom).
4. Fill in the fields:
   - **Name**: StremioArrs (or whatever you prefer)
   - **URL**: You can add all addons together or configure them as independent indexers (Recommended):
     - All at once (Aggregated mode): `http://localhost:5100/api`
     - Only Torrentio: `http://localhost:5100/torrentio/api`
     - Only Comet: `http://localhost:5100/comet/api`
     - Only Peerflix: `http://localhost:5100/peerflix/api`
     - Only ThePirateBay+: `http://localhost:5100/thepiratebay-plus/api`
     
     *(Change `localhost` to the local IP of your NAS/Server if it's on another machine, e.g., `http://192.168.1.100:5100/torrentio/api`)*
   - **API Key**: Leave blank (not required).
   - **Categories**: 
     - For Radarr: `2000, 2010` (Movies)
     - For Sonarr: `5000, 5030, 5040` (TV)
5. Click **Test** to verify the connection, then click **Save**.

## 🛠️ Local Development (Python)

If you want to run it without Docker:

```bash
# Clone the repository
git clone https://github.com/uniextra/StremioArrs.git
cd StremioArrs

# Install dependencies
pip install -r requirements.txt # (flask, requests)

# Set your OMDb API Key
export OMDB_API_KEY="your_omdb_api_key_here"

# Run the app
python main.py
```

## 📝 License
This project is licensed under the MIT License.
