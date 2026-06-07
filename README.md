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

Exercises are loaded from two files:

- `config/intervals.yaml`
- `config/harmonies.yaml`

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
