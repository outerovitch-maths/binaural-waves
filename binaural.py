#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.22", "scipy>=1.8"]
# ///
"""Génère un fichier WAV stéréo de battements binauraux pour dormir.

Oreille gauche = fréquence porteuse, oreille droite = porteuse + battement.
Les segments bouclent sur la liste des fréquences de battement jusqu'à la
durée totale demandée.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

# --- Paramètres par défaut ---------------------------------------------------
CARRIER_HZ = 100.0          # fréquence porteuse (oreille gauche)
BEATS_HZ = [5.0, 4.0, 3.0]  # fréquences de battement, jouées en boucle
SEGMENT_S = 10.0            # durée de chaque segment
DURATION_MIN = 10.0         # durée totale
SWAP = False                # inverse gauche/droite à chaque segment
VOLUME = 0.3                # amplitude, entre 0 et 1
OUTPUT = "sleep.wav"         # utilisé sans --play ni --output

SAMPLE_RATE = 44100
SEGMENT_FADE_S = 0.5        # fondu d'entrée/sortie de chaque segment
GLOBAL_FADE_S = 5.0         # fondu au début et à la fin du fichier
MPV_CMD = ["mpv", "--loop-file=inf", "--no-video"]  # lecture en boucle
# -----------------------------------------------------------------------------


def fade_envelope(n, fade_len):
    """Enveloppe 1.0 avec rampes (demi-cosinus) de fade_len échantillons aux bords."""
    env = np.ones(n)
    fade_len = min(fade_len, n // 2)
    if fade_len > 0:
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade_len))
        env[:fade_len] = ramp
        env[n - fade_len:] = ramp[::-1]
    return env


def generate(carrier, beats, segment_s, duration_s, swap, volume, sr=SAMPLE_RATE):
    """Retourne un tableau int16 de forme (n, 2) et la liste des segments générés."""
    total = int(round(duration_s * sr))
    seg_len = int(round(segment_s * sr))
    seg_fade = int(round(SEGMENT_FADE_S * sr))
    global_fade = min(int(round(GLOBAL_FADE_S * sr)), total // 2)

    out = np.empty((total, 2), dtype=np.int16)
    # Phase suivie par oreille pour rester continue d'un segment à l'autre.
    phase = np.zeros(2)
    segments = []

    start = 0
    i = 0
    while start < total:
        n = min(seg_len, total - start)
        beat = beats[i % len(beats)]
        freqs = np.array([carrier, carrier + beat])
        if swap and i % 2 == 1:
            freqs = freqs[::-1]

        t = np.arange(n) / sr
        signal = np.sin(phase + 2 * np.pi * np.outer(t, freqs))
        phase = (phase + 2 * np.pi * freqs * n / sr) % (2 * np.pi)

        env = fade_envelope(n, seg_fade)
        # Fondu global, appliqué sur la portion de ce segment qui le recoupe.
        idx = np.arange(start, start + n)
        env *= np.clip(idx / global_fade, 0.0, 1.0) if global_fade else 1.0
        env *= np.clip((total - 1 - idx) / global_fade, 0.0, 1.0) if global_fade else 1.0

        out[start:start + n] = np.round(signal * (env * volume * 32767)[:, None])
        segments.append((beat, swap and i % 2 == 1))
        start += n
        i += 1

    return out, segments


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--carrier", type=float, default=CARRIER_HZ,
                   help=f"fréquence porteuse en Hz (défaut {CARRIER_HZ:g})")
    p.add_argument("--beats", type=float, nargs="+", default=BEATS_HZ,
                   help="fréquences de battement en Hz (défaut %(default)s)")
    p.add_argument("--segment", type=float, default=SEGMENT_S,
                   help=f"durée d'un segment en secondes (défaut {SEGMENT_S:g})")
    p.add_argument("--duration", type=float, default=DURATION_MIN,
                   help=f"durée totale en minutes (défaut {DURATION_MIN:g})")
    p.add_argument("--swap", action="store_true", default=SWAP,
                   help="inverse gauche/droite à chaque segment")
    p.add_argument("--volume", type=float, default=VOLUME,
                   help=f"volume entre 0 et 1 (défaut {VOLUME:g})")
    p.add_argument("--output",
                   help=f"fichier WAV de sortie (défaut {OUTPUT}, ou fichier "
                        "temporaire supprimé après lecture avec --play)")
    p.add_argument("--play", action="store_true",
                   help="joue le fichier en boucle avec mpv après génération")
    args = p.parse_args(argv)

    if args.carrier <= 0:
        p.error("--carrier doit être > 0")
    if any(b <= 0 for b in args.beats):
        p.error("--beats : chaque fréquence doit être > 0")
    if args.segment <= 0:
        p.error("--segment doit être > 0")
    if args.duration <= 0:
        p.error("--duration doit être > 0")
    if not 0 <= args.volume <= 1:
        p.error("--volume doit être entre 0 et 1")
    if args.carrier + max(args.beats) >= SAMPLE_RATE / 2:
        p.error("fréquence trop élevée pour un échantillonnage à 44100 Hz")
    return args


def temp_wav():
    """Crée un fichier WAV vide dans le dossier temporaire et renvoie son chemin."""
    fd, path = tempfile.mkstemp(prefix="binaural-", suffix=".wav")
    os.close(fd)
    return Path(path)


def main(argv=None):
    args = parse_args(argv)
    duration_s = args.duration * 60
    data, segments = generate(args.carrier, args.beats, args.segment,
                              duration_s, args.swap, args.volume)

    # Écoute directe : fichier temporaire, supprimé une fois mpv fermé.
    temporary = args.play and args.output is None
    output = temp_wav() if temporary else Path(args.output or OUTPUT).resolve()
    try:
        return report_and_play(args, data, segments, duration_s, output, temporary)
    finally:
        if temporary:
            output.unlink(missing_ok=True)


def report_and_play(args, data, segments, duration_s, output, temporary):
    wavfile.write(output, SAMPLE_RATE, data)

    minutes, seconds = divmod(len(data) / SAMPLE_RATE, 60)
    print("Battements binauraux générés")
    print(f"  Durée        : {int(minutes)} min {seconds:04.1f} s "
          f"({len(segments)} segments de {args.segment:g} s"
          f"{', dernier écourté' if duration_s % args.segment else ''})")
    print(f"  Porteuse     : {args.carrier:g} Hz")
    print("  Battements   : " + ", ".join(
        f"{b:g} Hz (droite {args.carrier + b:g} Hz)" for b in args.beats))
    print(f"  Alternance   : {'oui (gauche/droite inversées un segment sur deux)' if args.swap else 'non'}")
    print(f"  Volume       : {args.volume:g}")
    print(f"  Fichier      : {output}{' (temporaire)' if temporary else ''}")

    if args.play:
        print("\nLecture en boucle avec mpv (q pour arrêter)…")
        try:
            return subprocess.run(MPV_CMD + [str(output)]).returncode
        except FileNotFoundError:
            print("mpv est introuvable, installe-le pour utiliser --play", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
