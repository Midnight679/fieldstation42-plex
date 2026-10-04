"""Questions and saved answers for the headless provisioner.

All questions are asked up front and the answers saved to a file, so the rest of the install runs unattended, a re-run
asks nothing it already knows, and another machine can be set up from the same file (`--answers FILE`).
The answers file holds the Plex token: it is written readable by its owner only.
"""

import getpass
import os
import re
import sys


class MissingAnswers(Exception):
    """Raised instead of asking when there is nobody to ask (no terminal) and an answer is missing."""

    def __init__(self, keys):
        super().__init__("Missing answers (no terminal to ask): " + ", ".join(keys))
        self.keys = list(keys)


class Answers:
    """KEY=value pairs kept in a small text file that is also easy to edit by hand."""

    def __init__(self, path=None):
        self.path = path
        self.values = {}
        self.reconfigure = False
        if path and os.path.exists(path):
            self._load(path)

    def _load(self, path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                self.values[key.strip()] = value

    def get(self, key, default=None):
        return self.values.get(key, default)

    def has(self, key):
        """True if the answer is known and should not be asked again."""
        return key in self.values and not self.reconfigure

    def set(self, key, value):
        self.values[key] = str(value)
        self.save()

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# FieldStation42 install answers (contains secrets: keep private)\n")
            for key, value in self.values.items():
                f.write(f"{key}={value}\n")
        os.chmod(self.path, 0o600)


class Asker:
    """The prompts. Input and output are replaceable so the questions can be tested."""

    def __init__(self, answers, interactive=None, input_fn=input, secret_fn=getpass.getpass, out=sys.stdout):
        self.answers = answers
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self.input = input_fn
        self.secret = secret_fn
        self.out = out

    def say(self, text=""):
        print(text, file=self.out)

    def _need_terminal(self, key):
        if not self.interactive:
            raise MissingAnswers([key])

    def _unattended_default(self, key, required, has_default):
        """With nobody to ask: True means "use the recommended default". Questions marked required, or with no
        default at all (a token, an address), are never guessed: they raise instead."""
        if self.interactive:
            return False
        if required or not has_default:
            raise MissingAnswers([key])
        return True

    def text(self, key, question, default=None, validate=None, secret=False, required=False):
        """Ask for a value (or use the saved answer). `validate(value)` returns an error message, or None if it is fine.
        Unattended, the default is used unless the question is `required` or has no default."""
        if self.answers.has(key):
            return self.answers.get(key)
        if self._unattended_default(key, required, default is not None and not secret):
            self.answers.set(key, default)
            return default
        suffix = f" [{default}]" if default and not secret else ""
        while True:
            reader = self.secret if secret else self.input
            value = reader(f"{question}{suffix}: ").strip()
            if not value and default is not None:
                value = default
            problem = validate(value) if validate else (None if value else "An answer is needed.")
            if problem:
                self.say(f"  {problem}")
                continue
            self.answers.set(key, value)
            return value

    def yes_no(self, key, question, default=True, required=False):
        if self.answers.has(key):
            return self.answers.get(key).lower() in ("1", "y", "yes", "true", "on")
        if self._unattended_default(key, required, True):
            self.answers.set(key, "yes" if default else "no")
            return default
        hint = "Y/n" if default else "y/N"
        while True:
            reply = self.input(f"{question} [{hint}]: ").strip().lower()
            if not reply:
                value = default
            elif reply in ("y", "yes"):
                value = True
            elif reply in ("n", "no"):
                value = False
            else:
                self.say("  Please answer y or n.")
                continue
            self.answers.set(key, "yes" if value else "no")
            return value

    def choice(self, key, question, options, default_index=0, required=False):
        """Pick from [(value, label), ...]. The saved answer is the value, so it survives a changed list order."""
        if self.answers.has(key):
            saved = self.answers.get(key)
            if any(v == saved for v, _ in options):
                return saved
        if self._unattended_default(key, required, True):
            self.answers.set(key, options[default_index][0])
            return options[default_index][0]
        self.say(question)
        for n, (_, label) in enumerate(options, 1):
            self.say(f"  {n}) {label}{'   (default)' if n - 1 == default_index else ''}")
        while True:
            reply = self.input(f"Choose 1-{len(options)} [{default_index + 1}]: ").strip()
            if not reply:
                n = default_index
            elif reply.isdigit() and 1 <= int(reply) <= len(options):
                n = int(reply) - 1
            else:
                self.say("  Please type one of the numbers.")
                continue
            self.answers.set(key, options[n][0])
            return options[n][0]


def check_plex_url(value):
    if not re.fullmatch(r"https?://[^\s/:]+(:\d+)?/?", value):
        return "That should look like http://192.168.1.10:32400 (address and port, no path)."
    return None
