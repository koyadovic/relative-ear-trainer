# Relative Ear Trainer - MIDI Ear Training App

Relative Ear Trainer is a free, open-source desktop ear training app for
musicians who want to practice relative pitch, interval recognition, chord
quality recognition, chord inversions, and harmonic function progressions. It is
built with Python, Tk, YAML configuration files, and General MIDI, so it runs on
a normal Linux desktop without a browser or DAW.

Use it as a lightweight interval trainer, chord ear trainer, jazz harmony
trainer, or configurable MIDI ear training tool.

## Features

- Interval ear training across two octaves with selectable ascending,
  descending, and harmonic modes.
- Harmony training for triads, seventh chords, extensions, altered chords,
  inversions, and selectable playback modes.
- Optional harmonic function training with configurable roman-numeral
  progressions.
- YAML-based exercises for adding custom intervals, chords, and progressions.
- Multi-select General MIDI instruments including piano, guitar, violin,
  vibraphone, marimba, flute, oboe, saxophone, trumpet, and sitar.
- Configurable comfortable MIDI ranges per instrument.
- Short, medium, and long playback durations.
- Persistent practice settings per tab.
- Persistent per-answer accuracy stats with a per-tab reset.
- Weighted challenge selection that favors answers with fewer previous attempts.
- Consecutive exact repeats are skipped when another playable challenge is available.

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

Exercises and instruments are loaded from four files:

- `config/intervals.yaml`
- `config/harmonies.yaml`
- `config/progressions.yaml`
- `config/instruments.yaml`

You can add entries without changing the Python code. Formulas use relative
scale degrees:

```yaml
harmonies:
  Maj7: "1, 3, 5, 7"
  "+": "1, 3, #5"
  m7b5: "1, b3, b5, b7"
```

Supported accidentals: `b`, `#`, including double accidentals such as `bb7`.
Compound intervals such as `b9`, `9`, `b10`, `10`, `b12`, `12`, `b13`, `13`,
`b14`, `14`, and `15` are calculated in the corresponding octave.

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

Instruments use General MIDI program numbers plus a comfortable note range:

```yaml
instruments:
  Piano: [0, 21, 108]
  Guitar: [24, 40, 88]
  Flute: [73, 60, 108]
```

The format is `[program, low_note, high_note]`. The app randomizes playback
among the instruments selected in the current tab, then picks roots that keep
the current interval, chord, inversion, or progression inside that instrument
range.

When the MIDI backend supports offline rendering, the app checks which pitches
actually produce audio for each configured instrument and stores that result in
the user settings. Training uses the central part of that effective pitch set,
discarding the lowest playable octave and the highest playable octave in every
tab. Intervals, harmonies, and harmonic function progressions only choose roots
whose notes are inside that final usable range. Backends that cannot be measured
use the central part of the YAML range instead.

## Saved Practice Sets

The app remembers the last UI settings for each training tab: selected material,
selected instruments, playback duration, interval modes, harmony modes, active
harmony inversions, and the active tab. This lets you start with a small group,
consolidate it, and gradually add more material without rebuilding the same
setup every time.

Each answer also tracks attempts, correct answers, and accuracy percentage.
Stats are saved per tab and can be reset from that tab without affecting the
others.

Settings and stats are saved in:

```text
~/.config/relative-ear-trainer/settings.json
```

You can override the settings path with `EAR_TRAINER_SETTINGS`.

Measured MIDI pitch sets are stored in the same settings file and are keyed by
the current MIDI backend and soundfont metadata, so they are recomputed when the
backend configuration changes.

## Feature Flags

The app shows only interval and harmony training by default. The harmonic
function trainer is still available but hidden while it is being refined.

Enable specific tabs with `EAR_TRAINER_TABS`:

```bash
EAR_TRAINER_TABS=intervals,harmonies,progressions ./app.sh
```

Supported tab keys are `intervals`, `harmonies`, and `progressions`.

## MIDI

The app generates temporary MIDI files and plays them with the first available
backend:

1. `fluidsynth` with a GM soundfont.
2. `timidity`.
3. `aplaymidi`, only if `EAR_TRAINER_MIDI_PORT` is set.

You can force a specific soundfont:

```bash
EAR_TRAINER_SOUNDFONT=/path/to/soundfont.sf2 ./app.sh
```

When using `timidity`, the app sends audio to the ALSA `default` output so it
works with PipeWire/PulseAudio setups. You can override that output device:

```bash
EAR_TRAINER_TIMIDITY_OUTPUT=plughw:0,0 ./app.sh
```

Each training tab has a `Duration` selector with `Short`, `Medium`, and `Long`
playback lengths.

## Search Terms

This project may be useful if you are looking for a relative pitch trainer,
interval ear trainer, chord inversion trainer, harmonic function ear training
app, jazz harmony trainer, MIDI ear training software, or a configurable Python
ear training tool for Linux.
