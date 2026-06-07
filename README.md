# Relative Ear Trainer

Aplicacion de escritorio simple para entrenar oido relativo con Python, Tk y MIDI General MIDI.

## Ejecutar

```bash
./run_app.sh
```

Requisitos habituales en Linux:

```bash
sudo apt install python3-tk fluidsynth fluid-soundfont-gm
```

`PyYAML` es opcional para estos ficheros simples. Si quieres sintaxis YAML completa:

```bash
python3 -m pip install -r requirements.txt
```

## Configuracion

Los ejercicios salen de dos ficheros:

- `config/intervals.yaml`
- `config/harmonies.yaml`

Puedes anadir entradas sin cambiar codigo. Las formulas usan grados relativos:

```yaml
harmonies:
  Maj7: "1, 3, 5, 7"
  "+": "1, 3, #5"
  m7b5: "1, b3, b5, b7"
```

Accidentales soportados: `b`, `#`, incluso dobles como `bb7`. Extensiones como `b9`,
`9`, `#11`, `b13` y `13` se calculan en la octava correspondiente.

## MIDI

La app genera ficheros MIDI temporales y los reproduce con el primer backend disponible:

1. `fluidsynth` con un soundfont GM.
2. `timidity`.
3. `aplaymidi`, solo si defines `EAR_TRAINER_MIDI_PORT`.

Puedes forzar un soundfont concreto:

```bash
EAR_TRAINER_SOUNDFONT=/ruta/a/soundfont.sf2 ./run_app.sh
```

