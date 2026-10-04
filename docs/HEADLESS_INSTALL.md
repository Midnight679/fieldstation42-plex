# Installing on a headless Ubuntu Server

`install/provision.sh` takes a fresh Ubuntu Server 24.04 (a Raspberry Pi 4, or an Intel mini PC) to a working player: the
packages, a minimal desktop with automatic login, the screen and sound settings, the Python environment, your Plex connection
and the service that starts the player at every boot. It asks a few questions first, then runs on its own.

```bash
git clone https://github.com/Midnight679/fieldstation42-plex
cd fieldstation42-plex
bash install/provision.sh
```

It takes about 20 to 40 minutes (mostly package downloads). On a real run it reopens itself inside `tmux`, so if your SSH
connection drops the install keeps going: `tmux attach -t fs42-setup` brings you back. Everything it prints is also saved in
`~/fs42-setup.log`.

## What it asks

Everything is asked up front, then saved, so the rest runs unattended.

- **Plex:** the server address and your token (typing the token is hidden). It checks the connection and shows your libraries
  with their item counts so you can see it is the right server. If you have more than one movie or TV library it asks which.
- **Screen:** which output the TV is on, and the resolution and refresh rate. It reads what the TV supports straight from the
  system and recommends 1080p, because a 4K picture overloads the player.
- **Sound:** which sound device to use. It lists them and picks the one on the same HDMI port as the screen.
- **Timezone** (schedules follow it), whether to **top schedules up automatically**, and whether to **restart when finished**.

## What it detects by itself

| Machine | What it does |
|---------|--------------|
| Raspberry Pi 4 or 400 | Keeps only files the Pi can decode (H.264 up to 1080p) out of the schedules, and sets the 1080p mode in both the X server and the kernel command line. |
| x86 mini PC (Intel) | Shows every file, since the GPU decodes H.264, HEVC, AV1 and 4K, and turns on hardware decoding. |
| Anything else (a Pi 5, another ARM board) | Stops and asks what to treat it as. It never guesses. |

## Saved answers

Answers are kept in `~/.config/fs42/install-answers.env` (readable only by you, because it holds the Plex token). A re-run
asks nothing it already knows. `--reconfigure` asks everything again, and `--answers FILE` uses another file. With a complete
file the install asks nothing at all, using the recommended defaults for the screen and sound settings it can detect. It still
stops for anything with no safe default (the Plex address and token, or an untested machine type).

## Options

```
--answers FILE    where answers are kept
--reconfigure     ask everything again
--phases a,b,c    run only some phases: detect, ask-plex, ask-display, packages, system, player, plex, mpv, ytdlp, services
--dry-run         show what would happen and change nothing
--root DIR        with --dry-run: write the files that would go in system folders into DIR, to look at them
```

`bash install/provision.sh --dry-run --root /tmp/fs42-preview` is a safe way to see exactly what it would do on your machine.

## Not included

Your channels, schedules and artwork are not part of the installer: copy your channel configs into `confs/` and rebuild with
`python3 station_42.py -r && python3 station_42.py -m` once the player is installed. The Raspberry Pi display and sound details
this installer sets up are explained in [install/systemd/README.md](../install/systemd/README.md), and the mini PC ones in
[X86_MINI_PC.md](X86_MINI_PC.md).

## Downloading a collection from the Internet Archive

`tools/archive_fetch.py` downloads the original video files of an Internet Archive item, several at a time. It resumes
interrupted downloads, skips files that are already complete, and checks every file against the Archive's checksum:

```bash
python3 tools/archive_fetch.py --item SOME-ITEM-ID --dest ~/media/clips --jobs 6
```
