# FieldStation42 systemd Services

FieldStation42 can run as systemd user services, which means:
- Automatically starts on login
- Runs in background (no terminal windows)
- Automatic restart on failure
- Centralized logging via systemd journal
- Easy management with systemctl commands

## Installation

**Important:** Only install systemd services after you have FieldStation42 configured and running stably. This is not part of the initial installation.

When ready, run:

```bash
bash install/install_services.sh
```

The installer will prompt you to select which services to enable:
- **Field Player** (fs42) - Core service, enabled by default
- **Web Console** (fs42-web) - Optional standalone web interface. Not needed with the Field Player, which already serves the web console on port 4242 (running both makes them fight over the port)
- **Cable Box** (fs42-cable-box) - Optional, for cable box interface
- **Remote Controller** (fs42-remote-controller) - Optional
- **OSD** (fs42-osd) - Optional, on-screen display overlay

Services are enabled but not started immediately. They will start automatically on next login, or you can start them manually.

## Plex credentials

If you use a Plex server (see [docs/PLEX.md](../../docs/PLEX.md)), put the connection details in a file outside the repo. The `fs42` and `fs42-web` services read it automatically if it exists:

```bash
mkdir -p ~/.config/fs42
cat > ~/.config/fs42/plex.env <<'EOT'
PLEX_URL=http://<plex-server-ip>:32400
PLEX_TOKEN=<your token>
EOT
chmod 600 ~/.config/fs42/plex.env
```

Restart after changing it: `systemctl --user restart fs42`.

## Minimal desktop on a headless install (e.g. Ubuntu Server)

The player needs an X display (`DISPLAY=:0`). The services do not need a full desktop environment, only a running X server: they wait up to two minutes for it at boot. On a server install with no desktop, a small auto-login X session is enough:

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y xorg openbox lightdm lightdm-gtk-greeter alsa-utils
sudo usermod -aG video,render,audio "$USER"
sudo mkdir -p /etc/lightdm/lightdm.conf.d
printf '[Seat:*]
autologin-user=%s
autologin-session=openbox
' "$USER" | sudo tee /etc/lightdm/lightdm.conf.d/50-fs42-autologin.conf
mkdir -p ~/.config/openbox
printf 'xset s off
xset -dpms
xset s noblank
' > ~/.config/openbox/autostart
sudo systemctl set-default graphical.target
sudo reboot
```

After the reboot (with the display connected), `DISPLAY=:0 xset q` from an SSH session should print the screen settings. Then run `bash install/install_services.sh` and start the services. For HDMI sound, check `aplay -l` for a `vc4hdmi` card.

## Managing Services

### Field Player (main service)

The field player is the core service that manages content playback. You'll restart this most often:

```bash
# Start
systemctl --user start fs42

# Stop
systemctl --user stop fs42

# Restart (most common)
systemctl --user restart fs42

# Check status
systemctl --user status fs42

# View logs
journalctl --user -u fs42 -f
```

### All Services

```bash
# Start all
systemctl --user start fs42-*

# Stop all
systemctl --user stop fs42-*

# Restart all
systemctl --user restart fs42-*

# Check status of all
systemctl --user status fs42-*

# View all logs
journalctl --user -u fs42-* -f
```

### Individual Services

- `fs42` - Field Player (main content playback)
- `fs42-web` - Standalone web console (only if you are not running `fs42`)
- `fs42-cable-box` - Cable Box interface
- `fs42-remote-controller` - Remote Controller
- `fs42-osd` - On-Screen Display (waits 30s before starting)

## Uninstall

```bash
bash install/uninstall_services.sh
```

## Raspberry Pi 4 on a minimal desktop: settings that matter

These are the things that bite on a Pi 4 running a bare-bones desktop (see the section above):

- **Run the screen at 1080p, set in the screen server, not afterwards.** A TV that supports 4K makes the Pi
  start the desktop at 3840x2160. mpv then scales everything to 4K on a GPU meant for 1080p, and the picture
  stutters or drops out. Changing the mode after the player has started leaves mpv with a stale window and
  a black picture (the sound keeps playing). Set the mode before anything starts:

  ```bash
  sudo mkdir -p /etc/X11/xorg.conf.d
  printf 'Section "Monitor"\n    Identifier "HDMI-1"\n    Option "PreferredMode" "1920x1080"\nEndSection\n' | sudo tee /etc/X11/xorg.conf.d/10-monitor.conf
  ```

  Use the output name `DISPLAY=:0 xrandr` shows as connected, if it is not `HDMI-1`.

- **Point mpv at the HDMI sound device.** mpv defaults to the headphone jack, so a TV stays silent.
  The Pi's HDMI audio only accepts stereo, which the `hdmi:` device handles. Find your card with
  `aplay -l`, test it with `speaker-test -D hdmi:CARD=vc4hdmi0,DEV=0 -c 2 -t wav -l 1`, then:

  ```bash
  mkdir -p ~/.config/mpv
  printf 'audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0\naudio-channels=stereo\n' > ~/.config/mpv/mpv.conf
  ```

- **Do not enable `fs42-osd` unless the desktop has a compositor.** The on-screen display is a transparent
  window. Without a compositor it draws as an opaque black box over the picture, so the sound plays and the
  video disappears when the overlay pops up. Say N to it in `install_services.sh`.

- **Only enable `fs42` (the Field Player).** It already serves the web console, so `fs42-web` is not needed.

- **Play only what the Pi can decode.** A Pi 4 handles H.264 up to 1080p. 4K, HEVC and AV1 files overload it,
  and a server without hardware transcoding cannot convert them live. See "Playing 4K and HEVC on a small
  device" in [docs/PLEX.md](../../docs/PLEX.md): set `PLEX_PLAYABLE_ONLY=true` and `PLEX_TRANSCODE=off`.

