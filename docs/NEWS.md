# News channel

A headline news channel in the style of the weather channel: a big current story with its summary, the section's other
headlines beside it, a scrolling ticker, a clock, and (optionally) the current temperature. Optionally it gives way to a
live newscast whenever one is on the air, and returns to the headlines when it ends.

The page is `fs42/fs42_server/static/news/news.html`. It reads public news feeds (RSS or Atom) through the FieldStation42
server (`/news/feed`), because a web page cannot read another site's feed directly. The server only fetches public web
addresses and refuses anything on the local network.

## Add it as a channel

A `web` channel, like the weather channel. Create `confs/news.json` (and the `catalog/news` folder, since every channel's
`content_dir` must exist):

```json
{
  "station_conf": {
    "network_name": "News",
    "network_type": "web",
    "channel_number": 17,
    "content_dir": "catalog/news",
    "web_url": "http://localhost:4242/static/news/news.html?config=runtime/news_config.json&lat=40.71&lon=-74.01&name=New%20York&units=f"
  }
}
```

## Settings (in the address)

| Setting | Meaning |
|---------|---------|
| `config` | A JSON file under the FieldStation42 folder listing the sections and feeds (below). Without it, a few general public feeds are used. |
| `lat`, `lon`, `name`, `units` | Optional. Show the current temperature (from Open-Meteo, no key) in the bottom bar. `units` is `f` (default) or `c`. |
| `rotate` | Seconds per story (default 14). |
| `music`, `volume` | Optional. A folder of audio files under the FieldStation42 folder, played shuffled, and its volume from 0 to 1 (default 0.25). |

## The feeds file

```json
{
  "sections": [
    {"title": "Top Stories", "count": 6, "feeds": ["https://example.com/news/rss.xml", "https://example.org/headlines.xml"]},
    {"title": "World",       "count": 6, "feeds": ["https://example.net/world.rss"]}
  ]
}
```

Each section shows `count` stories, taking one from each feed in turn so no outlet fills the section, and dropping repeated
headlines. The sections rotate in order, and all headlines also run along the ticker. Feeds are refreshed every ten minutes; if
a feed cannot be reached the last good headlines stay up.

## Switching to a live newscast

Give the channel a `streams_file` (the same file the live stream picker writes, see [LIVE_STREAMS.md](LIVE_STREAMS.md)):

```json
"streams_file": "runtime/news_live.json"
```

While that file lists a live stream, the channel plays it instead of the page (within about 30 seconds of it appearing).
When the stream ends or dies, or the list empties, the page comes back. Streams are listed highest priority first, and a stream
that would not play is skipped for ten minutes. The picker decides what is live; put the local stations you want in its
candidates file, using each station's YouTube channel `/live` address:

```json
{"candidates": [
  {"name": "Station one", "url": "https://www.youtube.com/@SomeStation/live", "priority": 100, "duration": 7200},
  {"name": "Station two", "url": "https://www.youtube.com/channel/CHANNEL_ID/live", "priority": 90, "duration": 7200}
], "fallback": []}
```

Run a picker for it (a second one if you also run a live stream channel), with its own relay port so the two do not clash:

```bash
python3 tools/live_stream_picker.py --candidates ~/news_candidates.json --out runtime/news_live.json --loop 120 --relay-port 8100
```

or as a user service the same way as in [LIVE_STREAMS.md](LIVE_STREAMS.md), with `--relay-port 8100` and its own file names.
Stations stream their newscasts at set times and for breaking news, so most of the day the channel shows the headlines.
