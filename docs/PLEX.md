# Plex content source

Instead of scanning folders, a station can build its catalog from your Plex server and stream items directly to mpv.

## Server config (`confs/main_config.json`)

```json
{ "plex": { "url": "http://192.168.1.50:32400", "token": "YOUR_PLEX_TOKEN" } }
```

`PLEX_URL` / `PLEX_TOKEN` environment variables override the file (preferred, so the token stays out of config files).

If you run FieldStation42 as systemd services, put them in `~/.config/fs42/plex.env` instead; see [install/systemd/README.md](../install/systemd/README.md).

## Station config

Add a `plex_sources` map. Each key is a **tag** (the same tag you use in the weekly schedule slots, or a `commercial_dir` / `bump_dir` value); each value says what in Plex that tag means:

```json
"plex_sources": {
  "Seinfeld":    { "library": "TV Shows", "show": "Seinfeld" },
  "80sAction":   { "library": "Movies",   "collection": "80s Action" }
}
```

Selectors (all of the ones you give must match, so each one narrows the result; give just `library` for everything in it):

| Selector | Meaning |
|----------|---------|
| `show` | One show by exact title |
| `titles` / `exclude_titles` | A list of exact titles to include / leave out |
| `title_contains` | Text (or a list of text) the title must contain |
| `genre` | A genre (or list; any one matches), e.g. `["Action", "Adventure"]` |
| `label` | A Plex label (or list) |
| `collection` | A Plex collection |
| `year_min` / `year_max` | Release year range |
| `ratings` | Allowed content ratings, e.g. `["G", "PG"]` (items with no rating never match) |

Titles and genres are case-insensitive. Run `tools/plex_check_station.py` (below) to see what each tag matches. Tags that are not in `plex_sources` are scanned from `content_dir` as usual, so you can mix local and Plex content.

## How it works

- Durations come from Plex, so no `ffprobe` pass is needed.
- The catalog stores `plex://<ratingKey>/<name>.mkv` paths; the real direct-play URL (with token) is resolved at playback time.
- Rebuild the catalog after changing Plex content, as with local folders.
- Commercials and bumps stay local. Leave them out of `plex_sources` and they are scanned from folders under `content_dir` exactly as upstream does.

## Recommended layout: Plex shows, local commercials and bumps

```json
{"station_conf": {
  "network_name": "plexTV",
  "channel_number": 2,
  "schedule_increment": 30,
  "break_strategy": "end",
  "content_dir": "catalog/plexTV",
  "commercial_dir": "commercial",
  "bump_dir": "bump",
  "plex_sources": {
    "Seinfeld": { "library": "TV Shows", "show": "Seinfeld" }
  },
  "monday": { "8": { "tags": "Seinfeld", "title": "Seinfeld" } }
}}
```

Put commercial clips in `catalog/plexTV/commercial/` and bumps in `catalog/plexTV/bump/` on the box. `content_dir` is still required because those folders are relative to it, but it doesn't need a `Seinfeld` folder. (Keep the `clip_shows`, sign-off and off-air settings from the upstream examples as needed.)

Shows and movies rarely fill their time slot exactly (a 91-minute movie in a 2-hour slot leaves about 29 minutes), and the gap is filled from the `bump` folder (or the `commercial` folder when `commercial_free` is `false`). If those folders are empty or missing, the gap is filled with your `be_right_back_media` image and a one-time warning is logged. Add short video clips to the folders to fill gaps properly.

## Seeing what's in your Plex

To list your libraries, titles, genres and collections (no credentials in the output) so you can plan channels:

```bash
set -a; source ~/.config/fs42/plex.env; set +a
python3 tools/plex_inventory.py > plex_inventory.txt
```

## Checking a channel before you rebuild

`tools/plex_check_station.py` is a dry run: it reads station configs, asks Plex what each tag matches, and prints the item count and hours per tag. It also flags tags that are scheduled but have no `plex_sources` entry.

```bash
set -a; source ~/.config/fs42/plex.env; set +a
python3 tools/plex_check_station.py confs/mychannel.json
```
