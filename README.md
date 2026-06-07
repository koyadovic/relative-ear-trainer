# Relative Ear Trainer - MIDI Ear Training App

Relative Ear Trainer is a free, open-source desktop ear training app for
musicians who want to practice relative pitch, interval recognition, chord
quality recognition, chord inversions, and harmonic function progressions. It is
built with Python, Tk, YAML configuration files, and General MIDI, so it runs on
a normal Linux desktop without a browser or DAW.

Use it as a lightweight interval trainer, chord ear trainer, jazz harmony
trainer, or configurable MIDI ear training tool.

## Features

- Interval ear training with ascending, descending, harmonic, and random modes.
- Harmony training for triads, seventh chords, extensions, altered chords, and
  inversions.
- Harmonic function training with configurable roman-numeral progressions.
- YAML-based exercises for adding custom intervals, chords, and progressions.
- General MIDI instruments including piano, guitar, violin, vibraphone, marimba,
  flute, oboe, saxophone, trumpet, sine wave, and sitar.
- Short, medium, and long playback durations.
- Persistent practice settings per tab.

## Run

```bash
./app.sh
```

Typical Linux requirements:

```bash
sudo apt install python3-tk fluidsynth fluid-soundfont-gm
```

`PyYAML` is optional for the bundled simple config files. Install it if you want
full YAML syntax support:

```bash
python3 -m pip install -r requirements.txt
```

## Configuration

Exercises are loaded from three files:

- `config/intervals.yaml`
- `config/harmonies.yaml`
- `config/progressions.yaml`

You can add entries without changing the Python code. Formulas use relative
scale degrees:

```yaml
harmonies:
  Maj7: "1, 3, 5, 7"
  "+": "1, 3, #5"
  m7b5: "1, b3, b5, b7"
```

Supported accidentals: `b`, `#`, including double accidentals such as `bb7`.
Extensions such as `b9`, `9`, `#11`, `b13`, and `13` are calculated in the
corresponding octave.

Progressions use roman numerals plus a harmony suffix. The suffix is resolved
from `config/harmonies.yaml`, so `IIm7` uses the `m7` harmony formula and
`V7b9` uses the `7b9` harmony formula:

```yaml
progressions:
  - "IIm7, V7, IMaj7"
  - "IIm7b5, V7b9, Im"
  - "bVIMaj7, bVII6, Im"
```

Roman degrees are based on the ionian major scale: `I`, `II`, `III`, `IV`, `V`,
`VI`, `VII`. Minor-mode progressions should write the natural-minor alterations
explicitly, for example `bIII`, `bVI`, and `bVII`.

The visible answer is the chord list itself.

Harmony answers include the chord quality plus the active voicing formula. For
example, a root-position major seventh appears as `Maj7 (1, 3, 5, 7)`, while
its first inversion appears as `Maj7 (3, 5, 7, 1)`.

## Saved Practice Sets

The app remembers the last UI settings for each training tab: selected material,
instrument, playback duration, mode, active harmony inversions, and the active
tab. This lets you start with a small group, consolidate it, and gradually add
more material without rebuilding the same setup every time.

Selections are saved in:

```text
~/.config/relative-ear-trainer/settings.json
```

You can override the settings path with `EAR_TRAINER_SETTINGS`.

## MIDI

The app generates temporary MIDI files and plays them with the first available
backend:

1. `fluidsynth` with a GM soundfont.
2. `timidity`.
3. `aplaymidi`, only if `EAR_TRAINER_MIDI_PORT` is set.

You can force a specific soundfont:

```bash
EAR_TRAINER_SOUNDFONT=/path/to/soundfont.sf2 ./run_app.sh
```

Each training tab has a `Duration` selector with `Short`, `Medium`, and `Long`
playback lengths.

## Search Terms

This project may be useful if you are looking for a relative pitch trainer,
interval ear trainer, chord inversion trainer, harmonic function ear training
app, jazz harmony trainer, MIDI ear training software, or a configurable Python
ear training tool for Linux.
