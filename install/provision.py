#!/usr/bin/env python3
"""Take a headless Ubuntu Server (Raspberry Pi 4 or an Intel mini PC) to a working FieldStation42 player.

Run it through the launcher, which keeps it going if your SSH connection drops:
    bash install/provision.sh
It asks its questions first (Plex, screen, sound, timezone), saves the answers, then runs unattended. Safe to run again.

    --answers FILE     where the answers are kept (default ~/.config/fs42/install-answers.env); with a complete file nothing is asked
    --reconfigure      ask everything again, offering the saved answers
    --phases a,b,c     run only these phases (default: all, in order): detect, ask-plex, ask-display, packages, system,
                       player, plex, mpv, ytdlp, services
    --dry-run          show what would happen and change nothing
    --root DIR         with --dry-run: write the files that would go under system folders into DIR instead, to inspect them
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provision_ask as ask  # noqa: E402
import provision_files as files  # noqa: E402
import provision_hw as hw  # noqa: E402

PHASES = ["detect", "ask-plex", "ask-display", "packages", "system", "player", "plex", "mpv", "ytdlp", "services"]
YT_DLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"


class Context:
    """Everything a phase needs, and the only place that touches the system (so --dry-run can intercept it)."""

    def __init__(self, repo, answers, asker, dry_run=False, root=None, home=None, user=None):
        self.repo = repo
        self.answers = answers
        self.asker = asker
        self.dry_run = dry_run
        self.root = root                     # a scratch folder standing in for "/" (dry runs only)
        self.user = user or os.environ.get("USER") or os.getlogin()
        self.home = home or os.path.expanduser("~")
        self.hw = None
        self.profile_kind = None

    @property
    def profile(self):
        return hw.profile_for(self.profile_kind)

    def say(self, text=""):
        print(text, flush=True)

    def step(self, text):
        print(f"\n==> {text}", flush=True)

    def _target(self, path):
        return os.path.join(self.root, path.lstrip("/")) if self.root else path

    def run(self, cmd, cwd=None, env=None, check=True):
        shown = " ".join(cmd) if isinstance(cmd, list) else cmd
        print(f"  $ {shown}", flush=True)
        if self.dry_run:
            return 0
        merged = dict(os.environ, **(env or {}))
        result = subprocess.run(cmd, cwd=cwd, env=merged, shell=isinstance(cmd, str))
        if check and result.returncode != 0:
            raise SystemExit(f"Command failed ({result.returncode}): {shown}")
        return result.returncode

    def write_system(self, path, content, mode=0o644):
        """Write a root-owned file (through sudo), or into the scratch root on a dry run."""
        print(f"  write {path}", flush=True)
        if self.root:
            target = self._target(path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return
        if self.dry_run:
            return
        subprocess.run(["sudo", "mkdir", "-p", os.path.dirname(path)], check=True)
        subprocess.run(["sudo", "tee", path], input=content.encode(), stdout=subprocess.DEVNULL, check=True)
        subprocess.run(["sudo", "chmod", oct(mode)[2:], path], check=True)

    def write_home(self, relpath, content, mode=0o644):
        path = os.path.join(self.home, relpath)
        print(f"  write {path}", flush=True)
        if self.dry_run and not self.root:
            return
        target = self._target(path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(target, mode)

    def read_system(self, path):
        try:
            with open(self._target(path), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""


# ---- Plex ----------------------------------------------------------------------------------------------------------

def plex_get(url, token, path, timeout=15, opener=urllib.request.urlopen):
    req = urllib.request.Request(url.rstrip("/") + path, headers={"X-Plex-Token": token, "Accept": "application/json"})
    with opener(req, timeout=timeout) as r:
        return json.load(r)


def plex_libraries(url, token, opener=urllib.request.urlopen):
    """[{"key", "title", "type", "count"}] for every library on the server. Raises on a bad address or token."""
    sections = plex_get(url, token, "/library/sections", opener=opener)["MediaContainer"].get("Directory", [])
    out = []
    for s in sections:
        count = None
        try:
            size = plex_get(url, token, f"/library/sections/{s['key']}/all?X-Plex-Container-Start=0&X-Plex-Container-Size=0",
                            opener=opener)
            count = size["MediaContainer"].get("totalSize")
        except Exception:
            pass
        out.append({"key": s["key"], "title": s["title"], "type": s["type"], "count": count})
    return out


# ---- phases --------------------------------------------------------------------------------------------------------

def phase_detect(ctx):
    ctx.step("Detecting this machine")
    ctx.hw = hw.detect_hardware(ctx.root or "/")
    ctx.say(f"  {ctx.hw['model']} ({ctx.hw['arch']})")
    kind = ctx.hw["kind"]
    if kind not in hw.PROFILES:
        kind = ctx.asker.choice(
            "HARDWARE_PROFILE",
            f"\nThis looks like a {ctx.hw['model']}, which has not been tested. Treat it like:",
            [("pi4", "a Raspberry Pi 4: only play files it can decode (H.264 up to 1080p)"),
             ("x86", "an Intel mini PC: play everything, with hardware decoding"),
             ("stop", "neither: stop here")], required=True)       # never guessed, even when unattended
        if kind == "stop":
            raise SystemExit("Stopped: this machine type is not supported yet.")
    ctx.profile_kind = kind
    ctx.say(f"  Setting it up as: {ctx.profile['label']}")


def phase_ask_plex(ctx):
    ctx.step("Plex")
    a, q = ctx.answers, ctx.asker
    if a.get("PLEX_SKIP", "no") == "yes" and not a.reconfigure:
        ctx.say("  Skipping Plex (set up earlier). Use --reconfigure to change that.")
        return
    while True:
        url = q.text("PLEX_URL", "Plex server address, for example http://192.168.1.10:32400", validate=ask.check_plex_url)
        token = q.text("PLEX_TOKEN", "Plex token (typing is hidden)", secret=True)
        try:
            libs = plex_libraries(url, token)
            break
        except Exception as e:
            ctx.say(f"  Could not read the Plex server: {e}")
            if not q.interactive:
                raise SystemExit("Plex check failed and there is nobody to ask. Fix the answers file or use PLEX_SKIP=yes.")
            if q.input("  Try different details? [Y/n] (n continues without Plex): ").strip().lower() in ("n", "no"):
                a.set("PLEX_SKIP", "yes")
                return
            for k in ("PLEX_URL", "PLEX_TOKEN"):
                a.values.pop(k, None)
    ctx.say("  Connected. Libraries on this server:")
    for lib in libs:
        ctx.say(f"    {lib['title']} ({lib['type']}): {lib['count'] if lib['count'] is not None else '?'} items")
    for kind, key, label in (("movie", "PLEX_MOVIE_LIBRARY", "movies"), ("show", "PLEX_SHOW_LIBRARY", "TV shows")):
        names = [lib["title"] for lib in libs if lib["type"] == kind]
        if not names:
            ctx.say(f"  (no {label} library found)")
            continue
        if len(names) == 1:
            a.set(key, names[0])
            ctx.say(f"  Using '{names[0]}' for {label}.")
        else:
            q.choice(key, f"Which library holds your {label}?", [(n, n) for n in names])


def phase_ask_display(ctx):
    ctx.step("Screen, sound and time")
    a, q = ctx.answers, ctx.asker
    outputs = hw.read_outputs(ctx.root or "/")
    connected = [o for o in outputs if o["connected"]]
    if connected:
        ctx.say("  Screens found: " + ", ".join(f"{o['connector']}" for o in connected))
    else:
        ctx.say("  No screen was detected (is the TV on and connected?). Using safe defaults you can change.")

    if len(connected) == 1 and not a.has("DISPLAY_CONNECTOR"):
        a.set("DISPLAY_CONNECTOR", connected[0]["connector"])      # only one screen: no need to ask which
    options = [(o["connector"], o["connector"]) for o in (connected or outputs)]
    if len(options) > 1:
        connector = q.choice("DISPLAY_CONNECTOR", "Which output is the TV on?", options)
    else:
        connector = q.text("DISPLAY_CONNECTOR", "Which video output is the TV on?",
                           default=options[0][0] if options else "HDMI-A-1")
    out = next((o for o in outputs if o["connector"] == connector), None)
    modes, default_mode = hw.resolution_choices(out["modes"] if out else [])
    default_value = f"{default_mode[0]}x{default_mode[1]}"
    choices = [(f"{w}x{h}", f"{w}x{h}" + ("  (recommended)" if f"{w}x{h}" == default_value else "")) for w, h in modes]
    if default_value not in dict(choices):
        choices.insert(0, (default_value, f"{default_value}  (recommended)"))
    default_index = [v for v, _ in choices].index(default_value)
    q.choice("DISPLAY_MODE", "Screen resolution (1080p is best: a 4K picture overloads the player):", choices, default_index)
    q.text("DISPLAY_REFRESH", "Refresh rate in Hz", default="60",
           validate=lambda v: None if v in ("24", "25", "30", "50", "60") else "Use 24, 25, 30, 50 or 60.")

    devices = hw.read_sound_devices(ctx.root or "/")
    if devices:
        suggested = hw.default_sound_device(devices, connector)
        labels = [(d["alsa"], f"{d['card']} / {d['name']}  ({d['alsa']})") for d in devices]
        di = next((i for i, d in enumerate(devices) if d is suggested), 0)
        q.choice("AUDIO_DEVICE", "Where should the sound go?", labels, di)
    else:
        q.text("AUDIO_DEVICE", "Sound device (no sound cards were found; ALSA name such as hdmi:CARD=vc4hdmi0,DEV=0)",
               default="hdmi:CARD=vc4hdmi0,DEV=0" if ctx.profile["is_pi"] else "hdmi:CARD=PCH,DEV=3")

    q.text("TIMEZONE", "Timezone (schedules follow it)", default=hw.current_timezone(ctx.root or "/"),
           validate=lambda v: None if hw.valid_timezone(v, ctx.root or "/")
           else "Not a known timezone name (for example America/New_York).")
    q.yes_no("SCHEDULE_AGENT", "Top schedules up automatically while it runs?", True)
    q.yes_no("REBOOT_WHEN_DONE", "Restart the computer when everything is installed?", True)


def phase_packages(ctx):
    ctx.step("Installing system packages (this takes a while)")
    ctx.run(["sudo", "apt-get", "update"])
    ctx.run("echo 'lightdm shared/default-x-display-manager select lightdm' | sudo debconf-set-selections")
    ctx.run(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y",
             "-o", "Dpkg::Options::=--force-confold"] + files.packages_for(ctx.profile_kind))


def phase_system(ctx):
    ctx.step("Display, sound and desktop")
    a = ctx.answers
    tz = a.get("TIMEZONE")
    if tz and tz != hw.current_timezone(ctx.root or "/"):
        ctx.run(["sudo", "timedatectl", "set-timezone", tz])
    ctx.run(["sudo", "usermod", "-aG", "video,render,audio", ctx.user])
    ctx.write_system("/etc/lightdm/lightdm.conf.d/50-fs42-autologin.conf", files.lightdm_autologin(ctx.user))
    ctx.write_home(".config/openbox/autostart", files.openbox_autostart())

    connector = a.get("DISPLAY_CONNECTOR", "HDMI-A-1")
    width, height = a.get("DISPLAY_MODE", "1920x1080").split("x")
    refresh = a.get("DISPLAY_REFRESH", "60")
    ctx.write_system("/etc/X11/xorg.conf.d/10-monitor.conf", files.xorg_monitor(connector, width, height))
    if ctx.profile["is_pi"]:
        for path in ("/boot/firmware/cmdline.txt", "/boot/cmdline.txt"):
            current = ctx.read_system(path)
            if current.strip():
                if not os.path.exists(ctx._target(path) + ".fs42bak") and not ctx.dry_run:
                    ctx.run(["sudo", "cp", "-n", path, path + ".fs42bak"])
                ctx.write_system(path, files.cmdline_with_video(current, connector, width, height, refresh))
                break
        else:
            ctx.say("  (no Pi kernel command line found; relying on the X server setting)")
    ctx.write_home(".asoundrc", files.asoundrc(a.get("AUDIO_DEVICE")))
    ctx.run(["sudo", "systemctl", "set-default", "graphical.target"])


def phase_player(ctx):
    ctx.step("FieldStation42 and its Python environment")
    ctx.run(["bash", "install.sh", "--yes"], cwd=ctx.repo)


def phase_plex(ctx):
    ctx.step("Plex connection and main settings")
    a = ctx.answers
    if a.get("PLEX_SKIP", "no") != "yes" and a.get("PLEX_URL"):
        ctx.write_home(".config/fs42/plex.env",
                       files.plex_env(a.get("PLEX_URL"), a.get("PLEX_TOKEN"), ctx.profile["playable_only"]), 0o600)
    path = os.path.join(ctx.repo, "confs", "main_config.json")
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    text = files.main_config(existing, a.get("SCHEDULE_AGENT", "yes") == "yes")
    print(f"  write {path}", flush=True)
    if not ctx.dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def phase_mpv(ctx):
    ctx.step("mpv settings")
    ctx.write_home(".config/mpv/mpv.conf", files.mpv_conf(ctx.answers.get("AUDIO_DEVICE"), ctx.profile["hwdec"]))


def install_ytdlp(ctx, opener=urllib.request.urlopen):
    asset = ctx.profile["yt_dlp_asset"]
    dest = os.path.join(ctx.home, ".local", "bin", "yt-dlp")
    ctx.say(f"  fetching {asset} -> {dest}")
    if ctx.dry_run:
        return
    sums = opener(YT_DLP_BASE + "SHA2-256SUMS", timeout=60).read().decode()
    expected = next((line.split()[0] for line in sums.splitlines() if line.split()[-1:] == [asset]), None)
    if not expected:
        raise SystemExit(f"No checksum for {asset} in the yt-dlp release; not installing it.")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest))
    h = hashlib.sha256()
    with os.fdopen(fd, "wb") as out, opener(YT_DLP_BASE + asset, timeout=120) as r:
        for block in iter(lambda: r.read(1 << 20), b""):
            h.update(block)
            out.write(block)
    if h.hexdigest() != expected:
        os.remove(tmp)
        raise SystemExit("The downloaded yt-dlp does not match its published checksum; not installing it.")
    os.chmod(tmp, 0o755)
    os.replace(tmp, dest)


def phase_ytdlp(ctx):
    ctx.step("yt-dlp (plays YouTube live streams)")
    install_ytdlp(ctx)


def phase_services(ctx):
    ctx.step("Starting the player at every boot")
    ctx.run(["sudo", "loginctl", "enable-linger", ctx.user])
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    ctx.run(["bash", "install/install_services.sh", "--yes", "--services", "fs42"], cwd=ctx.repo,
            env={"XDG_RUNTIME_DIR": f"/run/user/{uid}"})


RUNNERS = {"detect": phase_detect, "ask-plex": phase_ask_plex, "ask-display": phase_ask_display, "packages": phase_packages,
           "system": phase_system, "player": phase_player, "plex": phase_plex, "mpv": phase_mpv, "ytdlp": phase_ytdlp,
           "services": phase_services}


def keep_sudo_alive(stop):
    """A long install outlives sudo's password memory; refresh it quietly."""
    while not stop.wait(60):
        subprocess.run(["sudo", "-n", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_context(args, input_fn=input, secret_fn=None):
    repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    path = os.path.expanduser(args.answers)
    answers = ask.Answers(path)
    answers.reconfigure = args.reconfigure
    kwargs = {"input_fn": input_fn}
    if secret_fn:
        kwargs["secret_fn"] = secret_fn
    asker = ask.Asker(answers, **kwargs)
    return Context(repo, answers, asker, dry_run=args.dry_run, root=args.root)


def run_phases(ctx, phases):
    for name in phases:
        RUNNERS[name](ctx)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", default="~/.config/fs42/install-answers.env")
    ap.add_argument("--reconfigure", action="store_true")
    ap.add_argument("--phases", help="comma-separated phases to run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", help="with --dry-run: folder standing in for / so system files can be inspected")
    args = ap.parse_args(argv)
    if args.root:
        args.dry_run = True
    phases = args.phases.split(",") if args.phases else list(PHASES)
    unknown = [p for p in phases if p not in RUNNERS]
    if unknown:
        raise SystemExit(f"Unknown phase(s): {', '.join(unknown)}. Phases: {', '.join(PHASES)}")
    if "detect" not in phases and any(p != "detect" for p in phases):
        phases.insert(0, "detect")           # every other phase needs to know what kind of machine this is

    ctx = build_context(args)
    stop = threading.Event()
    if not args.dry_run and any(p in phases for p in ("packages", "system", "services")):
        subprocess.run(["sudo", "-v"], check=True)
        threading.Thread(target=keep_sudo_alive, args=(stop,), daemon=True).start()
    try:
        run_phases(ctx, phases)
    except ask.MissingAnswers as e:
        raise SystemExit(f"{e}\nRun it in a terminal, or add those answers to {args.answers}.")
    finally:
        stop.set()
    ctx.say("\nDone with: " + ", ".join(phases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
