# Weather channel

A local weather channel in the style of an early-2000s cable weather network, built as a web channel. It rotates
through four screens: current conditions, the next 12 hours, a 5-day forecast, and sunrise, sunset and today's
range. A ticker along the bottom summarizes the day, and a clock and date sit in the top bar.

The page is `fs42/fs42_server/static/weather/weather.html`. It reads live data from
[Open-Meteo](https://open-meteo.com), which is free and needs no account or key. The player's machine needs
internet access, and your coordinates are sent to Open-Meteo with each request (every 15 minutes).

## Add it as a channel

Create a station config (for example `confs/weather.json`) with your own coordinates. It is a `web` channel, like
the web guide, so it needs the same Qt WebEngine libraries (see the web channel notes in the install guides):

```json
{
  "station_conf": {
    "network_name": "Weather",
    "network_type": "web",
    "channel_number": 13,
    "content_dir": "catalog/weather",
    "web_url": "http://localhost:4242/static/weather/weather.html?lat=40.71&lon=-74.01&name=New%20York&units=f"
  }
}
```

Create the `catalog/weather` folder (every channel's `content_dir` must exist), and restart the player.

## Settings (in the address)

| Setting | Meaning |
|---------|---------|
| `lat`, `lon` | Your location in decimal degrees (required). Any maps site shows them for a place. |
| `name` | The place name shown on screen. Spaces are written `%20`. |
| `units` | `f` for Fahrenheit and mph (default), or `c` for Celsius and km/h. |
| `rotate` | Seconds each screen stays up (default 14). |
| `bg` | Optional. Comma-separated image names from the `bg/` folder, to use instead of the automatic scenes. |
| `music` | Optional. A folder of audio files under the FieldStation42 folder (for example `runtime/weather_music`), played shuffled and quietly. |
| `volume` | Music volume from 0 to 1 (default 0.3). |

If the data cannot be fetched, the channel shows a short message and retries. Once it has data, a later failed
refresh keeps showing the last good forecast.

## Backgrounds

Behind the panels, slow-fading mountain scenes match the real time of day (dawn, day, dusk, night) and the weather
(clear, cloudy, fog, rain, snow, storm), two shapes of each, 48 images in `bg/`. They are original artwork drawn by
`tools/weather_backgrounds.py` (`pip install pillow numpy`), so there is nothing to license. Run the script again to
redraw them, or edit it to change the look.

## Preview it on a computer

Serve the folder over HTTP and open it in a browser (opening the file directly will not run its scripts):

```bash
cd fs42/fs42_server/static/weather && python3 -m http.server 8765
# then open http://localhost:8765/weather.html?lat=40.71&lon=-74.01&name=New%20York
```
