#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.22", "scipy>=1.8"]
# ///
"""Interface clavier (curses) pour régler et générer les battements binauraux."""

import curses
import os
import subprocess
import time
from pathlib import Path

from scipy.io import wavfile

import binaural

BEAT_PRESETS = [
    [5.0, 4.0, 3.0],
    [6.0, 5.0, 4.0],
    [4.0, 3.0, 2.0],
    [3.0, 2.0, 1.5],
    [2.0, 1.5, 1.0],
    [7.0, 6.0, 5.0, 4.0],
    [4.0],
    [2.0],
]

# clé, libellé, type, pas, grand pas, min, max, unité
FIELDS = [
    ("carrier", "Porteuse", "num", 5, 50, 50, 1500, "Hz"),
    ("beats", "Battements", "beats", None, None, None, None, "Hz"),
    ("segment", "Segment", "num", 1, 10, 1, 600, "s"),
    ("duration", "Durée totale", "num", 1, 10, 0.5, 600, "min"),
    ("swap", "Alterner G/D", "bool", None, None, None, None, ""),
    ("volume", "Volume", "num", 0.05, 0.1, 0, 1, ""),
    ("output", "Fichier", "text", None, None, None, None, ""),
    ("play", "[ ▶ Jouer en boucle ]", "action", None, None, None, None, ""),
]


def fmt_num(v):
    return f"{v:g}"


def fmt_value(state, key):
    v = state[key]
    if key == "beats":
        return " → ".join(fmt_num(b) for b in v)
    if key == "swap":
        return "oui" if v else "non"
    if key == "output":
        return v or "(temporaire)"
    return fmt_num(v)


def parse_beats(text):
    beats = [float(x) for x in text.replace(",", " ").split()]
    if not beats or any(not 0 < b <= 100 for b in beats):
        raise ValueError("battements entre 0 et 100 Hz")
    return beats


def safe_addstr(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if 0 <= y < h and x < w:
        try:
            win.addstr(y, x, text[: w - x - 1], attr)
        except curses.error:
            pass


def edit_line(win, y, x, initial):
    """Petit éditeur de ligne. Renvoie le texte, ou None si Échap."""
    curses.curs_set(1)
    buf = list(initial)
    pos = len(buf)
    try:
        while True:
            safe_addstr(win, y, x, " " * (win.getmaxyx()[1]))
            safe_addstr(win, y, x, "".join(buf), curses.A_UNDERLINE)
            win.move(y, min(x + pos, win.getmaxyx()[1] - 2))
            ch = win.get_wch()
            if ch in ("\n", "\r", curses.KEY_ENTER):
                return "".join(buf)
            if ch == "\x1b":
                return None
            if ch in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                if pos > 0:
                    pos -= 1
                    del buf[pos]
            elif ch == curses.KEY_DC:
                if pos < len(buf):
                    del buf[pos]
            elif ch == curses.KEY_LEFT:
                pos = max(0, pos - 1)
            elif ch == curses.KEY_RIGHT:
                pos = min(len(buf), pos + 1)
            elif ch == curses.KEY_HOME:
                pos = 0
            elif ch == curses.KEY_END:
                pos = len(buf)
            elif isinstance(ch, str) and ch.isprintable():
                buf.insert(pos, ch)
                pos += 1
    finally:
        curses.curs_set(0)


def step_num(value, step, lo, hi, direction):
    new = round((value + direction * step) / step) * step
    return round(min(hi, max(lo, new)), 6)


def generate(state, output):
    duration_s = state["duration"] * 60
    data, segments = binaural.generate(state["carrier"], state["beats"],
                                       state["segment"], duration_s,
                                       state["swap"], state["volume"])
    wavfile.write(output, binaural.SAMPLE_RATE, data)
    return len(data) / binaural.SAMPLE_RATE, len(segments)


class Player:
    """Lecture en boucle avec mpv, en arrière-plan."""

    def __init__(self):
        self.proc = None
        self.path = None
        self.temp = None  # fichier d'écoute directe, supprimé en quittant

    def temp_path(self):
        if self.temp is None:
            self.temp = binaural.temp_wav()
        return self.temp

    def cleanup(self):
        self.stop()
        if self.temp is not None:
            self.temp.unlink(missing_ok=True)

    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def play(self, path):
        self.stop()
        self.proc = subprocess.Popen(binaural.MPV_CMD + ["--really-quiet", str(path)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
        self.path = path

    def stop(self):
        if self.playing():
            self.proc.terminate()
            self.proc.wait()
        self.proc = None


def draw(win, state, sel, message, player):
    win.erase()
    safe_addstr(win, 0, 2, "Battements binauraux", curses.A_BOLD)
    label_w = max(len(f[1]) for f in FIELDS) + 2
    for i, (key, label, kind, *_rest, unit) in enumerate(FIELDS):
        y = 2 + i + (1 if kind == "action" else 0)
        attr = curses.A_REVERSE if i == sel else 0
        if kind == "action":
            safe_addstr(win, y, 2, label, attr | curses.A_BOLD)
            continue
        safe_addstr(win, y, 2, label.ljust(label_w))
        value = fmt_value(state, key)
        if kind in ("num", "beats", "bool"):
            value = f"‹ {value} ›"
        safe_addstr(win, y, 2 + label_w, f"{value} {unit}".rstrip(), attr)

    y = 4 + len(FIELDS)
    right = ", ".join(fmt_num(state["carrier"] + b) for b in state["beats"])
    n_seg = -(-state["duration"] * 60 // state["segment"])
    safe_addstr(win, y, 2, f"Gauche {fmt_num(state['carrier'])} Hz · droite {right} Hz"
                f" · {int(n_seg)} segments", curses.A_DIM)

    kind = FIELDS[sel][2]
    hints = {
        "num": "←/→ ajuster · PgPréc/PgSuiv grand pas · Entrée saisir",
        "beats": "←/→ préréglages · Entrée saisir (ex. 5 4 3)",
        "bool": "←/→ ou Espace basculer",
        "text": "Entrée modifier (vide = temporaire, supprimé en quittant)",
        "action": "Entrée générer et jouer",
    }[kind]
    safe_addstr(win, y + 2, 2, f"↑/↓ choisir · {hints}", curses.A_DIM)
    safe_addstr(win, y + 3, 2, "p jouer en boucle · s stop · g générer sans jouer · q quitter",
                curses.A_DIM)
    if player.playing():
        safe_addstr(win, y + 5, 2, f"♪ Lecture en boucle : {player.path}", curses.A_BOLD)
    if message:
        safe_addstr(win, y + 6, 2, message[0], message[1])
    win.refresh()


def main(stdscr):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    ok, err = curses.color_pair(1), curses.color_pair(2)
    stdscr.keypad(True)

    state = {
        "carrier": binaural.CARRIER_HZ,
        "beats": list(binaural.BEATS_HZ),
        "segment": binaural.SEGMENT_S,
        "duration": binaural.DURATION_MIN,
        "swap": binaural.SWAP,
        "volume": binaural.VOLUME,
        "output": "",  # vide : fichier temporaire pour l'écoute directe
    }
    sel = 0
    message = None
    player = Player()
    try:
        loop(stdscr, state, sel, message, player, ok, err)
    finally:
        player.cleanup()


def loop(stdscr, state, sel, message, player, ok, err):
    while True:
        draw(stdscr, state, sel, message, player)
        ch = stdscr.get_wch()
        key, _label, kind, step, big, lo, hi, _unit = FIELDS[sel]
        message = None

        if ch in ("q", "Q", "\x1b"):
            return
        if ch == curses.KEY_UP:
            sel = (sel - 1) % len(FIELDS)
        elif ch == curses.KEY_DOWN or ch == "\t":
            sel = (sel + 1) % len(FIELDS)
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_PPAGE, curses.KEY_NPAGE, " "):
            direction = 1 if ch in (curses.KEY_RIGHT, curses.KEY_PPAGE) else -1
            if kind == "num":
                s = big if ch in (curses.KEY_PPAGE, curses.KEY_NPAGE) else step
                state[key] = step_num(state[key], s, lo, hi, direction)
            elif kind == "bool":
                state[key] = not state[key]
            elif kind == "beats":
                try:
                    idx = BEAT_PRESETS.index(state["beats"])
                except ValueError:
                    idx = -1 if direction > 0 else 0
                state["beats"] = list(BEAT_PRESETS[(idx + direction) % len(BEAT_PRESETS)])
        elif ch in ("s", "S"):
            player.stop()
        elif ch in ("\n", "\r", curses.KEY_ENTER, "g", "G", "p", "P"):
            if kind == "action" or ch in ("g", "G", "p", "P"):
                play = ch not in ("g", "G")
                # mpv ne doit pas lire le fichier pendant qu'on le réécrit.
                player.stop()
                message = ("Génération en cours…", curses.A_BOLD)
                draw(stdscr, state, sel, message, player)
                try:
                    t0 = time.monotonic()
                    if state["output"]:
                        path = Path(state["output"]).expanduser().resolve()
                    elif play:
                        path = player.temp_path()
                    else:
                        # Générer sans jouer n'a de sens qu'avec un vrai fichier.
                        path = Path(binaural.OUTPUT).resolve()
                    secs, n = generate(state, path)
                    m, s = divmod(secs, 60)
                    message = (f"✓ {path} — {int(m)} min {s:04.1f} s, {n} segments "
                               f"({time.monotonic() - t0:.1f} s)", ok)
                    if play:
                        player.play(path)
                except FileNotFoundError as e:
                    message = (f"✗ Introuvable : {e.filename}", err)
                except Exception as e:
                    message = (f"✗ Erreur : {e}", err)
            elif kind == "bool":
                state[key] = not state[key]
            else:
                y = 2 + sel
                x = 2 + max(len(f[1]) for f in FIELDS) + 2
                initial = state[key] if kind == "text" else fmt_value(state, key)
                text = edit_line(stdscr, y, x, initial.replace(" → ", " "))
                if text is None:
                    continue
                try:
                    if kind == "beats":
                        state[key] = parse_beats(text)
                    elif kind == "text":
                        state[key] = text.strip()  # vide : temporaire
                    else:
                        v = float(text.replace(",", "."))
                        if not lo <= v <= hi:
                            raise ValueError(f"valeur entre {fmt_num(lo)} et {fmt_num(hi)}")
                        state[key] = v
                except ValueError as e:
                    message = (f"✗ Valeur refusée : {e}", err)


if __name__ == "__main__":
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
