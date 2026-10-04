"""The text of every config file the provisioner writes, as plain functions (so each can be tested on its own).

The settings here are the ones proven on a Raspberry Pi 4 and an Intel mini PC; the reasons are in install/systemd/README.md and
docs/X86_MINI_PC.md.
"""

import json
import re

from provision_hw import x_output_name

# managed files start with this, so a later run can tell its own files from ones someone edited by hand
MARK = "# Written by the FieldStation42 provisioner (install/provision.py)"

# the Qt WebEngine libraries the guide, weather and news pages need, and the minimal desktop
BASE_PACKAGES = [
    "git", "curl", "tmux", "mpv", "ffmpeg", "python3", "python3-pip", "python3-venv", "python3-tk", "alsa-utils",
    "xorg", "x11-xserver-utils", "openbox", "lightdm", "lightdm-gtk-greeter",
]
WEB_PACKAGES = [
    "libevent-2.1-7t64", "libnss3", "libnspr4", "libxkbfile1", "libxkbcommon-x11-0", "libxcb-cursor0",
    "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-render-util0", "libxcb-shape0", "libxcb-xinerama0",
    "libxcb-xkb1", "libxcomposite1", "libxdamage1", "libxrandr2", "libxtst6", "libgbm1", "libasound2t64",
    "libminizip1t64", "libwebp7", "libwebpmux3", "libwebpdemux2", "libopus0", "libxslt1.1", "libxshmfence1",
    "libdbus-1-3",
]
X86_PACKAGES = ["vainfo", "intel-media-va-driver"]


def packages_for(kind):
    return BASE_PACKAGES + WEB_PACKAGES + (X86_PACKAGES if kind == "x86" else [])


def lightdm_autologin(user):
    return f"[Seat:*]\nautologin-user={user}\nautologin-session=openbox\n"


def openbox_autostart():
    """Screen blanking off: a TV that goes black on a timer is not a TV channel."""
    return f"{MARK}\nxset s off\nxset -dpms\nxset s noblank\n"


def xorg_monitor(connector, width, height):
    """Fix the mode in the X server, before anything starts: a 4K TV otherwise starts the desktop at 4K and the player stutters."""
    name = x_output_name(connector)
    return (f'{MARK}\n'
            f'Section "Monitor"\n    Identifier "{name}"\n    Option "PreferredMode" "{width}x{height}"\nEndSection\n')


def cmdline_with_video(text, connector, width, height, refresh):
    """A Raspberry Pi's kernel command line (one line) with the mode set for the connector, replacing any earlier setting."""
    words = [w for w in text.split() if not w.startswith(f"video={connector}:")]
    words.append(f"video={connector}:{width}x{height}@{refresh}")
    return " ".join(words) + "\n"


def mpv_conf(audio_device, hwdec=None, langs="en,eng,english"):
    lines = [f"audio-device=alsa/{audio_device}", "audio-channels=stereo", f"alang={langs}", f"slang={langs}",
             "subs-with-matching-audio=no", "image-display-duration=inf"]
    if hwdec:
        lines.insert(0, f"hwdec={hwdec}")
    return "\n".join(lines) + "\n"


def asoundrc(audio_device):
    """Make the system default sound device the same screen: web pages are drawn by a browser that ignores mpv's setting."""
    m = re.match(r"\w+:CARD=([^,]+)", audio_device)
    if not m:
        raise ValueError(f"not an ALSA device string: {audio_device}")
    card = m.group(1)
    return (f'pcm.!default {{\n  type plug\n  slave.pcm "{audio_device}"\n}}\n'
            f'ctl.!default {{\n  type hw\n  card {card}\n}}\n')


def plex_env(url, token, playable_only):
    lines = [f"PLEX_URL={url}", f"PLEX_TOKEN={token}", "PLEX_TRANSCODE=off"]
    if playable_only:
        lines.append("PLEX_PLAYABLE_ONLY=true")
    return "\n".join(lines) + "\n"


def main_config(existing_text, schedule_agent):
    """confs/main_config.json: keep whatever is there, make sure the seek timeout is long enough for streams, add the agent."""
    try:
        conf = json.loads(existing_text) if existing_text.strip() else {}
    except ValueError:
        conf = {}
    conf.setdefault("video_seek_timeout", 30)
    if schedule_agent:
        conf.setdefault("schedule_agent", {"amount_to_add": "month", "trigger_add_at": "week"})
    return json.dumps(conf, indent=2) + "\n"
