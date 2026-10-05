# Running FieldStation42 on an x86 mini PC (Intel)

A Raspberry Pi 4 can decode H.264 up to 1080p in hardware. Anything else (HEVC, AV1, 4K) overloads it, so the
Pi can only play part of a typical Plex library. A small Intel PC has a real GPU with hardware decoding for
H.264, HEVC (including 10-bit), AV1 and 4K, so every file plays directly and nothing has to be filtered out or
converted on the Plex server. The on-screen display (the channel popup) also works, because a normal desktop
stack has a compositor.

Everything in this fork is plain software and moves over unchanged: the code, your channel configs, your
credentials file and the guide theme.

## Hardware

- An Intel N100 / N150 class mini PC (Alder Lake-N or newer) with 8 GB of RAM.
- HDMI to the TV. Wired Ethernet is better than Wi-Fi for streaming.
- A TV or monitor connected at boot, so the desktop picks a sensible mode.

## 1. Install the operating system

Ubuntu Server 24.04 LTS is the simplest base, and it matches the setup this fork was tested on. Use the
minimal desktop below rather than a full desktop environment.

## 2. Install the packages

```bash
sudo apt-get update
sudo apt-get install -y git mpv ffmpeg python3 python3-pip python3-venv python3-tk alsa-utils \
    xorg openbox lightdm lightdm-gtk-greeter picom \
    vainfo intel-media-va-driver
```

For the web-based guide channel (Qt WebEngine), also install its libraries:

```bash
sudo apt-get install -y libevent-2.1-7t64 libnss3 libnspr4 libxkbfile1 libxkbcommon-x11-0 libxcb-cursor0 \
    libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    libxcomposite1 libxdamage1 libxrandr2 libxtst6 libgbm1 libasound2t64 libminizip1t64 libwebp7 libwebpmux3 \
    libwebpdemux2 libopus0 libxslt1.1 libxshmfence1 libdbus-1-3
```

## 3. Auto-login to a minimal desktop

```bash
sudo usermod -aG video,render,audio "$USER"
sudo mkdir -p /etc/lightdm/lightdm.conf.d
printf '[Seat:*]\nautologin-user=%s\nautologin-session=openbox\n' "$USER" | sudo tee /etc/lightdm/lightdm.conf.d/50-fs42-autologin.conf
mkdir -p ~/.config/openbox
printf 'xset s off\nxset -dpms\nxset s noblank\npicom --config ~/.config/picom/picom.conf -b\n' > ~/.config/openbox/autostart
mkdir -p ~/.config/picom
printf 'backend = "glx";\nvsync = true;\nshadow = false;\nfading = false;\nunredirect-if-possible = false;\n' > ~/.config/picom/picom.conf
sudo systemctl set-default graphical.target
```

If the TV is 4K, run the screen at 1080p. Set it in the screen server rather than after the desktop starts
(see the Raspberry Pi section of [install/systemd/README.md](../install/systemd/README.md)).

## 4. Install FieldStation42

```bash
git clone https://github.com/Midnight679/fieldstation42-plex
cd fieldstation42-plex
bash install.sh
```

Watch the output for packages that failed to install.

## 5. Plex credentials

Put the connection details in a file outside the repository:

```bash
mkdir -p ~/.config/fs42
printf 'PLEX_URL=http://<plex-server-ip>:32400\nPLEX_TOKEN=<your token>\n' > ~/.config/fs42/plex.env
chmod 600 ~/.config/fs42/plex.env
```

Do not set `PLEX_PLAYABLE_ONLY` here: the hardware decodes everything, so nothing needs filtering. Leave
`PLEX_TRANSCODE` unset (off) so the Plex server never has to convert video.

## 6. Hardware decoding

Check that the GPU's decoder is available. `vainfo` should list profiles such as `HEVCMain10` and `H264`:

```bash
vainfo
```

Then tell mpv to use it, and pick the HDMI sound device. List devices with `mpv --audio-device=help`:

```bash
mkdir -p ~/.config/mpv
printf 'hwdec=auto-safe\naudio-device=alsa/hdmi:CARD=PCH,DEV=3\n' > ~/.config/mpv/mpv.conf
```

The audio device name varies by machine; use one from the list for your HDMI output. Newer Intel machines use the
"SOF" sound driver (the card is called something like `sofhdadsp`); for those the `hdmi:` names do not exist and mpv
plays no sound. Use `plughw:` instead, for example `audio-device=alsa/plughw:CARD=sofhdadsp,DEV=3` (the output that has a
screen attached shows the screen's name in `aplay -l`), and point the system default at the same device in `~/.asoundrc`
so the web channels have sound too (the provisioner does both). To confirm hardware
decoding is active while a channel plays, ask mpv:

```bash
cd ~/fieldstation42-plex && source env/bin/activate
python3 -c 'from python_mpv_jsonipc import MPV; m=MPV(start_mpv=False, ipc_socket="runtime/mpv.socket"); print(m.command("get_property","hwdec-current"))'
```

A value such as `vaapi` or `vaapi-copy` means it works. `no` means software decoding.

## 7. Your channels and the services

Copy your channel configs into `confs/`, any channel art into `runtime/`, then build:

```bash
python3 station_42.py -r && python3 station_42.py -m
```

Install the services. Answer **Y** for the Field Player (`fs42`) and the On-Screen Display (`fs42-osd`) and **N** to
the rest. The web console is already part of the player, so `fs42-web` is not needed:

```bash
bash install/install_services.sh
```

Reboot, and the channels should start on their own with the channel popup working over the picture.

## Notes

- HDR content is tone-mapped by mpv for an SDR display. If colors look washed out, try `tone-mapping=bt.2390`
  in `~/.config/mpv/mpv.conf`.
- If a 4K TV drives the desktop at 4K, the GPU copes, but 1080p output is still a safer choice for smooth playback.
- Run `python3 tools/plex_media_report.py` to see the codec mix in your library.
