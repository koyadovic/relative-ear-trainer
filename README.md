# Relative Ear Trainer

A simple desktop app for relative ear training, built with Python, Tk, and General MIDI.

## Run

```bash
./run_app.sh
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

## Saved Practice Sets

The app remembers the last selected interval, harmony, and progression sets.
This lets you start with a small group, consolidate it, and gradually add more
material.

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
