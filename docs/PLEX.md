# Plex content source

Instead of scanning folders, a station can build its catalog from your Plex server and stream items directly to mpv.

## Server config (`confs/main_config.json`)

```json
{ "plex": { "url": "http://<plex-server-ip>:32400", "token": "YOUR_PLEX_TOKEN" } }
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

## Playing 4K and HEVC on a small device (Raspberry Pi 4)

A Pi 4 can play H.264 up to 1080p, and HEVC (H.265) only at 720p or below (see `PLEX_HEVC_MAX_HEIGHT`); 4K, larger HEVC and AV1 are out. When a Plex item has
no version the player can handle, the fork can ask Plex to convert it on the fly to a 1080p H.264 stream,
starting at the point in the schedule that is currently on air. Plex does the heavy lifting on the server.

Set these as environment variables (for example in `~/.config/fs42/plex.env`), or as keys of the `plex`
block in `confs/main_config.json` (`transcode`, `max_height`, `max_bitrate`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `PLEX_TRANSCODE` | `off` | `off` never transcodes, `auto` only when no playable version exists, `always` every time |
| `PLEX_MAX_HEIGHT` | `1080` | Tallest picture the player can handle, and the transcode size |
| `PLEX_MAX_BITRATE` | `10000` | Transcode target in kbps |
| `PLEX_MAX_DIRECT_BITRATE` | `25000` | Highest bitrate in kbps still played directly (1080p H.264 is well within a Pi 4's hardware decoder) |
| `PLEX_HEVC_MAX_HEIGHT` | `720` | Tallest HEVC (H.265) picture played directly. A Pi 4 has no usable hardware HEVC decode under stock mpv, so its CPU does the work: about 4x real time at 720p, only about 2x at 1080p. `0` turns HEVC off (also the `hevc_max_height` key). A mini PC can raise it, e.g. `2160` (still capped by `PLEX_MAX_HEIGHT`) |
| `PLEX_PLAYABLE_ONLY` | off | `true` leaves out of the catalog any item with no version the player can decode directly (also a per-source `"playable_only"` setting) |

Whatever the mode, if an item has several versions (for example a 4K and a 1080p copy), the best
version within these limits is chosen for direct play. Transcodes take a few seconds to start, so also set
`"video_seek_timeout": 30` in `confs/main_config.json`. Plex needs enough CPU or GPU to transcode in real
time. The fork asks Plex to end the previous transcode when the next one starts, so changing channels does
not leave sessions running.

Live transcoding needs a server that can convert video in real time. A server with no hardware
transcoding (an older machine, or a NAS) usually cannot convert 4K HEVC fast enough, and Plex may refuse or
stall. In that case set `PLEX_TRANSCODE=off` and `PLEX_PLAYABLE_ONLY=true`: only items the player can decode
directly are scheduled, and heavy items join the channels automatically once a playable copy exists
(for example a 1080p H.264 file made with Plex's Optimized Versions, HandBrake or ffmpeg). Rebuild the
catalogs after adding copies. `tools/plex_transcode_test.py` checks whether your server accepts transcode
requests, and `tools/plex_check_station.py` shows how many items each tag keeps.

To see how much of your library needs this, run `tools/plex_media_report.py`. It prints the codec and
resolution mix of each library and lists the heaviest files, without playing anything.

## Choosing audio and subtitle languages

Many files carry several audio and subtitle tracks, and the file's own default is often the original language
(for example Japanese audio on anime). mpv picks tracks by language, so set a preference in
`~/.config/mpv/mpv.conf`. This prefers English audio, and shows English subtitles only when the audio is not
English (the last line needs a recent mpv; check with `mpv --list-options | grep subs-with-matching-audio`):

```
alang=en,eng,english
slang=en,eng,english
subs-with-matching-audio=no
```

It applies to every channel. Files with no English track play as before. To see which tracks a file has while
it plays, ask mpv:

```bash
cd ~/fieldstation42-plex && source env/bin/activate
python3 - <<'EOF'
from python_mpv_jsonipc import MPV
m = MPV(start_mpv=False, ipc_socket="runtime/mpv.socket")
for t in m.command("get_property", "track-list"):
    if t.get("type") in ("audio", "sub"):
        print(t["type"], t.get("id"), t.get("lang"), t.get("title"), "SELECTED" if t.get("selected") else "")
EOF
```

## Commercial breaks inside a show

FieldStation42 normally finds the places to cut a show for a break by scanning the video file on disk. Plex
items are not local files, so this fork supplies the cut points itself:

- **Chapters from Plex.** When the catalog is built, each item's chapter markers are fetched once and stored
  where the scheduler looks for break points, so breaks land at chapter boundaries (usually scene changes).
  Items already stored are skipped on later rebuilds. Use `--reset_chapters` to fetch them again, and
  `--skip_chapter_scan` to skip the lookup entirely.
- **Long chapters are subdivided.** Plex items often have only a few chapters, and the scheduler spreads the ad time
  evenly over the cut points it has, so two or three chapters would mean a few very long breaks. Any chapter longer than
  four minutes is split into equal pieces, so there are always enough places to cut and breaks stay short.
- **Even splits for everything else.** An item with fewer than two chapters is divided into equal parts, with
  a break after each part.
- Items shorter than five minutes are never cut.

Use `"break_strategy": "standard"` and a `"break_duration"` (seconds per break, for example `120`) in the station
config. With `"break_strategy": "end"` every break plays after the show instead. To see how many of your items
carry chapters, run `tools/plex_chapters_report.py`.

To see how a program is laid out (show parts and the length of each ad break), run `python3 tools/show_plan.py <channel>`.
Use a `schedule_increment` of `10` so a show that runs a little long gets a block only slightly longer than itself, instead of
being rounded up to the next half hour with that whole gap filled with ads.

## Playing a show in order

A schedule slot with `"sequence"` plays a tag's episodes in order instead of at random, and remembers where it got to
(see the Sequences section of `STATION_CONFIG_README.md`). It works with Plex tags too: the episodes are ordered by
season and episode, from season 1 episode 1, and the sequence loops when it reaches the end.

```json
"day_templates": { "weekday": { "20": { "tags": "Seinfeld", "sequence": "in-order" } } }
```

Use one tag per show (a tag that mixes several shows is ordered by title, not by show). Episodes the player cannot
decode are left out when `playable_only` is on, so the sequence skips over them. The sequence is rebuilt from the
catalog, so rebuild the catalog after changing Plex content.

## A file that will not play

A damaged file (one Plex could not analyse, an incomplete download) cannot start, and the player used to retry it every
second with a black screen. Now a file that fails to start twice in a row is skipped for 30 minutes: the channel shows its
stand-by picture for the time that file was scheduled, then carries on with the next entry (commercials, the next show).
After 30 minutes it gets another try, so a file that was only unreachable comes back by itself. The log says
`Giving up on <file>` when this happens. To find damaged files, look for items in Plex that have no video or audio details
(Analyze in Plex's menu shows whether it can read them), and replace the file.
