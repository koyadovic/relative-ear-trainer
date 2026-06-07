from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
import tkinter as tk
from tkinter import messagebox, ttk

from .config_loader import ConfigError
from .midi import MidiNote, MidiPlayer, PlaybackError
from .music import MusicDefinition, load_harmony_definitions, load_interval_definitions
from .settings import SettingsStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERVALS_PATH = PROJECT_ROOT / "config" / "intervals.yaml"
HARMONIES_PATH = PROJECT_ROOT / "config" / "harmonies.yaml"

TIMBRES = {
    "Piano": 0,
    "Guitar": 24,
    "Violin": 40,
    "Vibraphone": 11,
    "Marimba": 12,
    "Flute": 73,
    "Oboe": 68,
    "Saxophone": 65,
    "Trumpet": 56,
    "Sine wave": 80,
    "Sitar": 104,
}
TIMBRE_COLUMNS = 6
RANDOM_LABEL = "Random"
INTERVAL_MODES = ("Ascending", "Descending", "Harmonic", RANDOM_LABEL)


@dataclass(frozen=True)
class Challenge:
    answer: str
    program: int
    notes: list[MidiNote]


class EarTrainerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Relative Ear Trainer")
        self.minsize(860, 620)

        try:
            interval_definitions = load_interval_definitions(INTERVALS_PATH)
            harmony_definitions = load_harmony_definitions(HARMONIES_PATH)
        except ConfigError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            raise

        self.player = MidiPlayer()
        self.settings = SettingsStore()
        self._configure_style()

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)
        notebook.add(
            IntervalTrainerTab(notebook, self.player, self.settings, interval_definitions),
            text="Intervals",
        )
        notebook.add(
            HarmonyTrainerTab(notebook, self.player, self.settings, harmony_definitions),
            text="Harmonies",
        )

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.configure("Header.TLabel", font=("", 12, "bold"))
        style.configure("Result.TLabel", font=("", 12, "bold"))


class BaseTrainerTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        settings_key: str,
        definitions: tuple[MusicDefinition, ...],
        title: str,
    ) -> None:
        super().__init__(parent, padding=12)
        self.player = player
        self.settings = settings
        self.settings_key = settings_key
        self.definitions = definitions
        self.title = title
        self.running = False
        self.current: Challenge | None = None
        self.correct_count = 0
        self.total_count = 0
        self._selection_save_after_id: str | None = None

        self.timbre_var = tk.StringVar(value=RANDOM_LABEL)
        self.status_var = tk.StringVar(value=f"MIDI: {self.player.describe_backend()}")
        self.score_var = tk.StringVar(value="Correct: 0/0")
        selected_names = self.settings.selected_names(
            self.settings_key,
            [definition.name for definition in self.definitions],
        )
        self.selection_vars = {}
        for definition in self.definitions:
            selected = True if selected_names is None else definition.name in selected_names
            self.selection_vars[definition.name] = tk.BooleanVar(value=selected)
        self.answer_buttons: dict[str, ttk.Button] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        self._build_header()
        self._build_definition_selector()
        self._build_answer_area()
        self._build_controls()
        self._set_answer_buttons_enabled(False)
        self._bind_selection_persistence()

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=self.title, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        timbre_frame = ttk.LabelFrame(header, text="Instrument", padding=8)
        timbre_frame.grid(row=0, column=1, sticky="e")
        for index, label in enumerate((*TIMBRES.keys(), RANDOM_LABEL)):
            row, column = divmod(index, TIMBRE_COLUMNS)
            ttk.Radiobutton(
                timbre_frame,
                text=label,
                value=label,
                variable=self.timbre_var,
            ).grid(row=row, column=column, padx=4, sticky="w")

    def _build_definition_selector(self) -> None:
        outer = ttk.LabelFrame(self, text="Selection", padding=8)
        outer.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        buttons = ttk.Frame(outer)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(buttons, text="All", command=lambda: self._set_all_selections(True)).pack(
            side=tk.LEFT
        )
        ttk.Button(buttons, text="None", command=lambda: self._set_all_selections(False)).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        grid_parent = self._scrollable_frame(outer, height=145)
        for index, definition in enumerate(self.definitions):
            row, column = divmod(index, 6)
            ttk.Checkbutton(
                grid_parent,
                text=definition.name,
                variable=self.selection_vars[definition.name],
            ).grid(row=row, column=column, sticky="w", padx=8, pady=3)

    def _build_answer_area(self) -> None:
        outer = ttk.LabelFrame(self, text="Answer", padding=8)
        outer.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        grid_parent = self._scrollable_frame(outer, height=185)
        for index, definition in enumerate(self.definitions):
            row, column = divmod(index, 6)
            button = ttk.Button(
                grid_parent,
                text=definition.name,
                command=lambda name=definition.name: self._answer(name),
            )
            button.grid(row=row, column=column, sticky="ew", padx=5, pady=4)
            grid_parent.columnconfigure(column, weight=1, minsize=100)
            self.answer_buttons[definition.name] = button

    def _build_controls(self) -> None:
        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(footer, text="Start", command=self._toggle_running)
        self.start_button.grid(row=0, column=0, padx=(0, 6))
        self.replay_button = ttk.Button(
            footer,
            text="Replay",
            command=self._replay_current,
            state=tk.DISABLED,
        )
        self.replay_button.grid(row=0, column=1, padx=(0, 10))
        ttk.Label(footer, textvariable=self.status_var, style="Result.TLabel").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Label(footer, textvariable=self.score_var).grid(row=0, column=3, sticky="e")

    def _scrollable_frame(self, parent: tk.Widget, height: int) -> ttk.Frame:
        container = ttk.Frame(parent)
        _columns, next_row = parent.grid_size()
        container.grid(row=next_row, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, height=height, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def update_scroll_region(_event: tk.Event[tk.Widget]) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event: tk.Event[tk.Widget]) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)
        return inner

    def _set_all_selections(self, selected: bool) -> None:
        for variable in self.selection_vars.values():
            variable.set(selected)

    def _bind_selection_persistence(self) -> None:
        for variable in self.selection_vars.values():
            variable.trace_add("write", lambda *_args: self._queue_selection_save())

    def _queue_selection_save(self) -> None:
        if self._selection_save_after_id is not None:
            self.after_cancel(self._selection_save_after_id)
        self._selection_save_after_id = self.after(250, self._save_selection)

    def _save_selection(self) -> None:
        self._selection_save_after_id = None
        selected_names = [
            definition.name
            for definition in self.definitions
            if self.selection_vars[definition.name].get()
        ]
        try:
            self.settings.save_selected_names(self.settings_key, selected_names)
        except OSError as exc:
            self.status_var.set(f"Could not save selection: {exc}")

    def _active_definitions(self) -> list[MusicDefinition]:
        return [
            definition
            for definition in self.definitions
            if self.selection_vars[definition.name].get()
        ]

    def _toggle_running(self) -> None:
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        if not self._active_definitions():
            self.status_var.set("Select at least one option")
            return

        self._save_selection()
        self.running = True
        self.correct_count = 0
        self.total_count = 0
        self.score_var.set("Correct: 0/0")
        self.start_button.configure(text="Stop")
        self.replay_button.configure(state=tk.NORMAL)
        self._next_challenge()

    def _stop(self) -> None:
        self.running = False
        self.current = None
        self.start_button.configure(text="Start")
        self.replay_button.configure(state=tk.DISABLED)
        self._set_answer_buttons_enabled(False)
        self.status_var.set("Stopped")

    def _next_challenge(self) -> None:
        if not self.running:
            return

        active_definitions = self._active_definitions()
        if not active_definitions:
            self._stop()
            self.status_var.set("Select at least one option")
            return

        definition = random.choice(active_definitions)
        self.current = self._build_challenge(definition)
        self._set_answer_buttons_enabled(True)
        self.status_var.set("Listen")
        self._play_current()

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        raise NotImplementedError

    def _choose_program(self) -> int:
        timbre_name = self.timbre_var.get()
        if timbre_name == RANDOM_LABEL:
            timbre_name = random.choice(tuple(TIMBRES))
        return TIMBRES[timbre_name]

    def _play_current(self) -> None:
        if self.current is None:
            return
        try:
            self.player.play(program=self.current.program, notes=self.current.notes)
        except PlaybackError as exc:
            self.status_var.set(str(exc))

    def _replay_current(self) -> None:
        self._play_current()

    def _answer(self, answer: str) -> None:
        if not self.running or self.current is None:
            return

        correct = answer == self.current.answer
        self.total_count += 1
        if correct:
            self.correct_count += 1
            self.status_var.set(f"Correct: {self.current.answer}")
        else:
            self.status_var.set(f"Wrong: it was {self.current.answer}")

        self.score_var.set(f"Correct: {self.correct_count}/{self.total_count}")
        self._set_answer_buttons_enabled(False)
        self.after(900, self._next_challenge)

    def _set_answer_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self.answer_buttons.values():
            button.configure(state=state)


class IntervalTrainerTab(BaseTrainerTab):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        definitions: tuple[MusicDefinition, ...],
    ) -> None:
        self.interval_mode_var = tk.StringVar(master=parent, value=RANDOM_LABEL)
        super().__init__(
            parent,
            player,
            settings,
            "intervals",
            definitions,
            title="Interval training",
        )

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=self.title, style="Header.TLabel").grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="w",
        )

        timbre_frame = ttk.LabelFrame(header, text="Instrument", padding=8)
        timbre_frame.grid(row=0, column=1, sticky="e")
        for index, label in enumerate((*TIMBRES.keys(), RANDOM_LABEL)):
            row, column = divmod(index, TIMBRE_COLUMNS)
            ttk.Radiobutton(
                timbre_frame,
                text=label,
                value=label,
                variable=self.timbre_var,
            ).grid(row=row, column=column, padx=4, sticky="w")

        mode_frame = ttk.LabelFrame(header, text="Mode", padding=8)
        mode_frame.grid(row=1, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(INTERVAL_MODES):
            ttk.Radiobutton(
                mode_frame,
                text=label,
                value=label,
                variable=self.interval_mode_var,
            ).grid(row=0, column=column, padx=4)

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        interval = definition.semitones[0]
        mode = self.interval_mode_var.get()
        if mode == RANDOM_LABEL:
            mode = random.choice(("Ascending", "Descending", "Harmonic"))

        pitch_class = random.randrange(12)
        if mode == "Ascending":
            root = 48 + pitch_class
            notes = [
                MidiNote(start=0, duration=440, pitch=root),
                MidiNote(start=560, duration=520, pitch=root + interval),
            ]
        elif mode == "Descending":
            root = 72 + pitch_class
            notes = [
                MidiNote(start=0, duration=440, pitch=root),
                MidiNote(start=560, duration=520, pitch=root - interval),
            ]
        else:
            root = 60 + pitch_class
            notes = [MidiNote(start=0, duration=960, pitch=root)]
            target = root + interval
            if target != root:
                notes.append(MidiNote(start=0, duration=960, pitch=target))

        return Challenge(answer=definition.name, program=self._choose_program(), notes=notes)


class HarmonyTrainerTab(BaseTrainerTab):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        definitions: tuple[MusicDefinition, ...],
    ) -> None:
        super().__init__(
            parent,
            player,
            settings,
            "harmonies",
            definitions,
            title="Harmony training",
        )

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        pitch_class = random.randrange(12)
        root = 48 + pitch_class
        notes = [
            MidiNote(start=0, duration=1280, pitch=root + semitone, velocity=84)
            for semitone in definition.semitones
        ]
        return Challenge(answer=definition.name, program=self._choose_program(), notes=notes)


def main() -> None:
    app = EarTrainerApp()
    app.mainloop()
