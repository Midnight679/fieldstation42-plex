# Guide promo panel

The grid guide (`customguide.html`, themes `90s`, `00s`, `y2k`) has a panel across the top that cycles through short
messages. With `videos=false` it can show a picture beside each message instead of a video.

Point the guide at a messages file with `messages=` in the channel's `web_url`:

```
http://localhost:4242/static/customguide/customguide.html?theme=y2k&slots=3&header=Guide&videos=false&messages=runtime/guide_messages.json
```

```json
{
  "messages": [
    { "title": "Now on <b>Movies</b>", "body": "Films all day. Channel 4.", "image": "runtime/channel_art/movies_logo.png" },
    { "title": "Stay tuned", "body": "The guide is always on Channel 1." }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `title` | Heading (may contain simple HTML such as `<b>`) |
| `body` | Text under it |
| `image` | Optional picture (png, jpg or webp) under the FieldStation42 folder, shown beside the text with a slow zoom. Landscape 16:9 works best. A message without one fades the picture out. |
| `duration` | Optional seconds to show the message (default comes from the theme) |

If no message has an `image` (and there are no videos), the picture panel is hidden as before.
