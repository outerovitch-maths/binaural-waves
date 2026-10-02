# Battements binauraux pour dormir

Génère un fichier WAV stéréo (44100 Hz, int16) de battements binauraux :
oreille gauche = porteuse, oreille droite = porteuse + battement. À écouter au casque.

## Installation

```bash
git clone https://github.com/outerovitch-maths/binaural-waves.git
cd binaural-waves
ln -s "$PWD/binaural" ~/.local/bin/binaural
```

Il suffit d'avoir [uv](https://docs.astral.sh/uv/) et, pour la lecture, mpv. Les dépendances (numpy, scipy) sont
déclarées dans les scripts et uv les installe lui-même au premier lancement.

## Utilisation

```bash
# Interface au clavier : ↑/↓ choisir, ←/→ ajuster, Entrée saisir,
# p jouer en boucle avec mpv, s stop, g générer sans jouer, q quitter (coupe la lecture)
binaural

# 10 min, porteuse 100 Hz, battements 5 → 4 → 3 Hz en boucle (valeurs par défaut),
# enregistré dans ./sleep.wav
binaural --duration 10

# Écoute directe en boucle avec mpv (q dans mpv pour arrêter) : le WAV est écrit
# dans le dossier temporaire (/tmp) et supprimé à la fin de la lecture
binaural --play

# Lecture en gardant le fichier
binaural --play --output sleep.wav

# 30 min en delta, segments de 20 s, oreilles alternées, volume plus bas
binaural --beats 3 2 1.5 --segment 20 --duration 30 --swap --volume 0.2 --output delta.wav
```

Sans argument, `binaural` ouvre l'interface (`tui.py`). Avec des arguments, il appelle
`binaural.py`. `binaural --help` liste toutes les options (`--duration` est en minutes,
`--segment` en secondes). Les scripts se lancent aussi directement : `./tui.py`, `./binaural.py`.

## Où va le fichier ?

| Cas | Fichier |
| --- | --- |
| `--play` sans `--output` | temporaire (`/tmp/binaural-*.wav`), supprimé quand mpv se ferme |
| sans `--play` ni `--output` | `./sleep.wav` |
| `--output chemin.wav` | `chemin.wav`, conservé |
| Interface, champ « Fichier » vide | lecture (`p`) : temporaire, supprimé en quittant ; `g` : `./sleep.wav` |
| Interface, champ « Fichier » rempli | ce fichier, conservé |
