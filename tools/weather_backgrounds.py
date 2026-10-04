#!/usr/bin/env python3
"""Draw the background scenes for the weather channel: layered mountain ridgelines, for every time of day and
every kind of weather.

    pip install pillow numpy
    python3 tools/weather_backgrounds.py                  # writes fs42/fs42_server/static/weather/bg/*.jpg
    python3 tools/weather_backgrounds.py --only night_rain

Four times of day (dawn, day, dusk, night) times six conditions (clear, cloudy, fog, rain, snow, storm), two
different ridge shapes of each, named like day_rain_1.jpg and day_rain_2.jpg. The scenes are original artwork made
by this script (no photographs, nothing to license). The weather page fades slowly between them, chosen by the
real sunrise, sunset and forecast.
"""

import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080

PHASES = {  # sky top, sky middle, horizon glow, haze colour, mountain base colour
    "dawn":  dict(top=(48, 62, 128), mid=(226, 128, 128), hor=(255, 205, 140), haze=(255, 190, 150), dark=(52, 48, 96)),
    "day":   dict(top=(48, 124, 220), mid=(120, 186, 242), hor=(205, 232, 252), haze=(196, 222, 248), dark=(30, 80, 114)),
    "dusk":  dict(top=(34, 40, 104), mid=(190, 86, 120), hor=(255, 168, 88), haze=(240, 140, 110), dark=(34, 30, 70)),
    "night": dict(top=(4, 8, 34), mid=(14, 30, 80), hor=(36, 62, 120), haze=(40, 70, 130), dark=(6, 12, 34)),
}
# desat: how far colours move toward grey; dim: brightness multiplier; clouds: amount; cloud_dark: 0 white .. 1 charcoal
CONDITIONS = {
    "clear":  dict(desat=0.0,  dim=1.0,  clouds=0.35, cloud_dark=0.0,  fog=0.0, rain=0, snow=0, bolt=False),
    "cloudy": dict(desat=0.45, dim=0.92, clouds=1.5,  cloud_dark=0.25, fog=0.0, rain=0, snow=0, bolt=False),
    "fog":    dict(desat=0.55, dim=1.0,  clouds=0.0,  cloud_dark=0.0,  fog=1.0, rain=0, snow=0, bolt=False),
    "rain":   dict(desat=0.6,  dim=0.72, clouds=1.7,  cloud_dark=0.6,  fog=0.35, rain=520, snow=0, bolt=False),
    "snow":   dict(desat=0.65, dim=0.95, clouds=1.3,  cloud_dark=0.15, fog=0.45, rain=0, snow=260, bolt=False),
    "storm":  dict(desat=0.55, dim=0.55, clouds=2.0,  cloud_dark=0.9,  fog=0.25, rain=680, snow=0, bolt=True),
}


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def grey_toward(col, desat, dim):
    g = int(0.3 * col[0] + 0.59 * col[1] + 0.11 * col[2])
    return tuple(int(c * dim) for c in mix(col, (g, g, g), desat))


def sky(p, rng):
    y = np.linspace(0, 1, H)[:, None]
    top, mid, hor = (np.array(p[k], dtype=float) for k in ("top", "mid", "hor"))
    t1, t2 = np.clip(y / 0.55, 0, 1), np.clip((y - 0.55) / 0.45, 0, 1)
    col = np.where(y < 0.55, top * (1 - t1) + mid * t1, mid * (1 - t2) + hor * t2)
    col = np.repeat(col[:, None, :], W, axis=1)
    col += rng.normal(0, 1.1, (H, W, 1))                       # dither: removes visible banding in the gradient
    return Image.fromarray(np.clip(col, 0, 255).astype(np.uint8), "RGB").convert("RGBA")


def smooth_noise(n_points, width, rng):
    pts = rng.random(n_points + 1)
    x = np.linspace(0, n_points, width, endpoint=False)
    i = x.astype(int)
    f = x - i
    f = f * f * (3 - 2 * f)
    return pts[i] * (1 - f) + pts[i + 1] * f


def ridge(base, amp, rng, octaves=6, rough=0.52):
    y = np.zeros(W)
    for o in range(octaves):
        y += smooth_noise(2 ** (o + 2), W, rng) * (rough ** o)
    y = (y - y.min()) / (y.max() - y.min())
    return base - y * amp


def soft_layer(color):
    """A transparent layer whose hidden pixels already carry the colour, so blurring never creates dark fringes."""
    return Image.new("RGBA", (W, H), tuple(color) + (0,))


def add_clouds(img, amount, dark, rng, base_tint):
    tint = mix(base_tint, (58, 62, 74), dark)
    layer = soft_layer(tint)
    d = ImageDraw.Draw(layer)
    for _ in range(int(26 * amount)):
        cx, cy = int(rng.integers(-100, W + 100)), int(rng.integers(20, int(H * 0.5)))
        for _ in range(int(rng.integers(5, 11))):
            rx, ry = int(rng.integers(80, 240)), int(rng.integers(24, 70))
            ox, oy = int(rng.integers(-170, 170)), int(rng.integers(-24, 24))
            alpha = int((55 + 60 * rng.random()) * (1.0 + 0.5 * dark))
            d.ellipse((cx + ox - rx, cy + oy - ry, cx + ox + rx, cy + oy + ry), fill=tint + (min(alpha, 230),))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(26)))


def add_rain(img, count, rng, bright):
    layer = soft_layer((200, 215, 235))
    d = ImageDraw.Draw(layer)
    for _ in range(count):
        x, y = int(rng.integers(-50, W)), int(rng.integers(0, H))
        ln = int(rng.integers(40, 95))
        d.line((x, y, x - int(ln * 0.18), y + ln), fill=(200, 215, 235, int(40 + 70 * rng.random() * bright)), width=2)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.8)))


def add_snow(img, count, rng):
    layer = soft_layer((255, 255, 255))
    d = ImageDraw.Draw(layer)
    for _ in range(count):
        x, y, r = int(rng.integers(0, W)), int(rng.integers(0, H)), int(rng.integers(2, 6))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, int(130 + 110 * rng.random())))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.2)))


def add_bolt(img, rng):
    x, y = int(rng.integers(int(W * 0.25), int(W * 0.75))), int(H * 0.08)
    pts = [(x, y)]
    while y < H * 0.5:
        x += int(rng.integers(-60, 60))
        y += int(rng.integers(35, 80))
        pts.append((x, y))
    glow = soft_layer((200, 210, 255))
    ImageDraw.Draw(glow).line(pts, fill=(235, 240, 255, 220), width=7)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(14)))
    core = soft_layer((255, 255, 255))
    ImageDraw.Draw(core).line(pts, fill=(255, 255, 255, 255), width=3)
    img.alpha_composite(core)


def scene(phase, cond, seed):
    p0, c = PHASES[phase], CONDITIONS[cond]
    rng = np.random.default_rng(seed)
    night = phase == "night"
    p = {k: grey_toward(p0[k], c["desat"], c["dim"]) for k in p0}
    if cond == "fog":                                   # a milky, flat sky
        for k in ("top", "mid", "hor"):
            p[k] = mix(p[k], p["haze"], 0.65)
    img = sky(p, rng)

    if night and cond == "clear":
        d = ImageDraw.Draw(img)
        for _ in range(420):
            x, y = int(rng.integers(0, W)), int(rng.random() ** 1.6 * H * 0.6)
            b = int(120 + 135 * rng.random())
            r = 1 if rng.random() < 0.85 else 2
            d.ellipse((x - r, y - r, x + r, y + r), fill=(b, b, min(255, b + 20), 255))
        mx, my = int(W * (0.62 + 0.2 * rng.random())), int(H * 0.2)
        glow = soft_layer((160, 190, 255))
        ImageDraw.Draw(glow).ellipse((mx - 170, my - 170, mx + 170, my + 170), fill=(160, 190, 255, 70))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
        ImageDraw.Draw(img).ellipse((mx - 46, my - 46, mx + 46, my + 46), fill=(238, 244, 255, 255))

    if c["clouds"] > 0:
        base_tint = (255, 255, 255) if phase == "day" else mix(p["hor"], (255, 255, 255), 0.25)
        if night:
            base_tint = mix(p["mid"], (150, 165, 200), 0.5)
        add_clouds(img, c["clouds"], c["cloud_dark"], rng, base_tint)
    if c["bolt"]:
        add_bolt(img, rng)

    layers = [(0.60, 150), (0.68, 190), (0.76, 220), (0.85, 230), (0.95, 250)]
    fog_amount = 0.12 + 0.55 * c["fog"]
    for i, (base, amp) in enumerate(layers):
        depth = 1 - i / (len(layers) - 1)                # 1 = farthest
        col = mix(p["dark"], p["haze"], 0.15 + 0.7 * depth ** 1.3)
        if cond == "snow":                               # snow-dusted ridges
            col = mix(col, (236, 242, 252) if not night else (120, 135, 170), 0.5 + 0.2 * depth)
        col = mix(col, p["haze"], fog_amount * (0.5 + 0.5 * depth))
        ys = ridge(H * base, amp, rng)
        poly = [(x, float(ys[x])) for x in range(0, W, 2)] + [(W, H), (0, H)]
        layer = soft_layer(col)
        ImageDraw.Draw(layer).polygon(poly, fill=col + (255,))
        if depth > 0.4:
            layer = layer.filter(ImageFilter.GaussianBlur(1.6 * depth))
        img.alpha_composite(layer)
        mist = soft_layer(p["haze"])
        band_y = int(H * (base + 0.09))
        ImageDraw.Draw(mist).rectangle((0, band_y, W, band_y + 70), fill=p["haze"] + (int(30 + 30 * depth + 80 * c["fog"]),))
        img.alpha_composite(mist.filter(ImageFilter.GaussianBlur(38)))

    if c["rain"]:
        add_rain(img, c["rain"], rng, 0.6 if night else 1.0)
    if c["snow"]:
        add_snow(img, c["snow"], rng)
    return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.join(here, "..", "fs42", "fs42_server", "static", "weather", "bg"))
    ap.add_argument("--only", help="just one scene, e.g. night_rain")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    n = 0
    for pi, phase in enumerate(PHASES):
        for ci, cond in enumerate(CONDITIONS):
            if args.only and args.only != f"{phase}_{cond}":
                continue
            for variant in (1, 2):
                path = os.path.join(args.out, f"{phase}_{cond}_{variant}.jpg")
                scene(phase, cond, seed=1000 + pi * 211 + ci * 37 + variant * 977).save(path, "JPEG", quality=80, optimize=True, progressive=True)
                n += 1
    print(f"wrote {n} scenes to {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
