"""Hardware, display, sound and timezone detection for the headless provisioner.

Everything here reads the system through plain files (/proc, /sys) under an optional `root`, so it works on a bare server with
no desktop running, and can be tested against a fake folder tree. No third-party packages.
"""

import os
import platform
import re

# What each kind of machine needs. "playable_only" keeps Plex items the machine cannot decode out of the schedules.
PROFILES = {
    "pi4": {
        "label": "Raspberry Pi 4",
        "is_pi": True,
        "playable_only": True,     # hardware decodes H.264 up to 1080p only
        "hwdec": None,
        "yt_dlp_asset": "yt-dlp_linux_aarch64",
    },
    "x86": {
        "label": "x86 mini PC",
        "is_pi": False,
        "playable_only": False,    # an Intel GPU decodes H.264, HEVC, AV1 and 4K
        "hwdec": "auto-safe",
        "yt_dlp_asset": "yt-dlp_linux",
    },
}


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def _p(root, path):
    return os.path.join(root, path.lstrip("/"))


# ---- the machine ---------------------------------------------------------------------------------------------------

def detect_hardware(root="/", machine=None):
    """{"kind": "pi4" | "x86" | "pi_other" | "unknown", "model": str, "arch": str}.

    pi_other (a Pi 5, Pi 3, ...) and unknown are not guessed at: the caller asks what to treat the machine as.
    """
    arch = machine or platform.machine()
    model = _read(_p(root, "/proc/device-tree/model")).strip("\x00 \n")
    if re.match(r"Raspberry Pi (4|400)\b|Raspberry Pi Compute Module 4", model):
        kind = "pi4"
    elif "Raspberry Pi" in model:
        kind = "pi_other"
    elif arch.lower() in ("x86_64", "amd64"):
        kind = "x86"
    else:
        kind = "unknown"
    return {"kind": kind, "model": model or f"{arch} computer", "arch": arch}


def profile_for(kind):
    return PROFILES[kind]


# ---- the screen ----------------------------------------------------------------------------------------------------

_CONNECTOR = re.compile(r"^card\d+-((?:HDMI|DP|DVI|VGA)[\w-]*)$")


def read_outputs(root="/"):
    """Video outputs the kernel knows: [{"connector", "connected", "modes": [(w, h), ...]}], preferred mode first."""
    drm = _p(root, "/sys/class/drm")
    outputs = []
    try:
        entries = sorted(os.listdir(drm))
    except OSError:
        return outputs
    for entry in entries:
        m = _CONNECTOR.match(entry)
        if not m:
            continue
        base = os.path.join(drm, entry)
        modes = []
        for line in _read(os.path.join(base, "modes")).splitlines():
            mm = re.fullmatch(r"(\d+)x(\d+)", line.strip())      # interlaced modes carry a trailing "i": skipped
            if mm and (int(mm.group(1)), int(mm.group(2))) not in modes:
                modes.append((int(mm.group(1)), int(mm.group(2))))
        outputs.append({"connector": m.group(1), "connected": _read(os.path.join(base, "status")).strip() == "connected",
                        "modes": modes})
    return outputs


def x_output_name(connector):
    """The kernel's connector name as the X server calls it: HDMI-A-1 -> HDMI-1, DP-1 -> DP-1."""
    return re.sub(r"-[A-Z]-", "-", connector)


def resolution_choices(modes, ceiling=2160):
    """Resolutions to offer (largest first, up to the ceiling) and the default: 1920x1080 if the screen has it."""
    shown = sorted({m for m in modes if m[1] <= ceiling}, key=lambda m: (-m[0] * m[1]))
    if not shown:
        return [(1920, 1080)], (1920, 1080)
    if (1920, 1080) in shown:
        return shown, (1920, 1080)
    below = [m for m in shown if m[1] <= 1080]
    return shown, (below[0] if below else shown[-1])


# ---- sound ---------------------------------------------------------------------------------------------------------

def read_sound_devices(root="/"):
    """Playback devices: [{"card": id, "card_name", "device": n, "name", "alsa": "hdmi:CARD=..,DEV=.." , "is_hdmi"}]."""
    devices = []
    text = _read(_p(root, "/proc/asound/cards"))
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", text, re.M):
        index, card_id, card_name = m.group(1), m.group(2), m.group(3).strip()
        card_dir = _p(root, f"/proc/asound/card{index}")
        try:
            pcms = sorted(d for d in os.listdir(card_dir) if re.fullmatch(r"pcm\d+p", d))
        except OSError:
            pcms = []
        for pcm in pcms:
            info = _read(os.path.join(card_dir, pcm, "info"))
            dev = re.search(r"^device:\s*(\d+)", info, re.M)
            name = re.search(r"^name:\s*(.*)$", info, re.M)
            dev_n = int(dev.group(1)) if dev else int(pcm[3:-1])
            pcm_name = name.group(1).strip() if name else pcm
            is_hdmi = "hdmi" in f"{card_id} {card_name} {pcm_name}".lower()
            # alsa-lib only defines its named "hdmi:" outputs for some drivers (the Pi's vc4 and Intel's classic HDA); on
            # others, such as the newer Intel SOF cards, "hdmi:CARD=..." does not exist and mpv plays nothing. "plughw:" works anywhere.
            driver = card_name.split(" - ")[0].strip().lower()
            named_hdmi = is_hdmi and (card_id.startswith("vc4hdmi") or driver == "hda-intel")
            devices.append({"card": card_id, "card_name": card_name, "device": dev_n, "name": pcm_name,
                            "alsa": f"{'hdmi' if named_hdmi else 'plughw'}:CARD={card_id},DEV={dev_n}", "is_hdmi": is_hdmi})
    return devices


def default_sound_device(devices, connector=None):
    """The sound device most likely to reach the screen: the HDMI card for that connector on a Pi, else the first HDMI one."""
    hdmi = [d for d in devices if d["is_hdmi"]]
    if connector:
        m = re.search(r"HDMI-A-(\d+)$", connector)
        if m:
            wanted = f"vc4hdmi{int(m.group(1)) - 1}"
            for d in hdmi:
                if d["card"] == wanted:
                    return d
    return (hdmi or devices or [None])[0]


# ---- timezone ------------------------------------------------------------------------------------------------------

def current_timezone(root="/"):
    name = _read(_p(root, "/etc/timezone")).strip()
    if name:
        return name
    try:
        target = os.readlink(_p(root, "/etc/localtime"))
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def valid_timezone(name, root="/"):
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}", name or ""):
        return False
    # a preview run points root at an empty folder, so the machine's own timezone database counts too
    return any(os.path.isfile(_p(r, f"/usr/share/zoneinfo/{name}")) for r in {root, "/"})
