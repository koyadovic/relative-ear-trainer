from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar
import os
import random
import tkinter as tk
from tkinter import messagebox, ttk

from .config_loader import ConfigError
from .midi import MidiNote, MidiPlayer, PlaybackError
from .music import (
    InstrumentDefinition,
    MusicDefinition,
    ProgressionDefinition,
    load_instrument_definitions,
    load_harmony_definitions,
    load_interval_definitions,
    load_progression_definitions,
)
from .settings import SettingsStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERVALS_PATH = PROJECT_ROOT / "config" / "intervals.yaml"
HARMONIES_PATH = PROJECT_ROOT / "config" / "harmonies.yaml"
PROGRESSIONS_PATH = PROJECT_ROOT / "config" / "progressions.yaml"
INSTRUMENTS_PATH = PROJECT_ROOT / "config" / "instruments.yaml"
ENABLED_TABS_ENV_VAR = "EAR_TRAINER_TABS"
TAB_INTERVALS = "intervals"
TAB_HARMONIES = "harmonies"
TAB_PROGRESSIONS = "progressions"
AVAILABLE_TAB_KEYS = (TAB_INTERVALS, TAB_HARMONIES, TAB_PROGRESSIONS)
DEFAULT_ENABLED_TAB_KEYS = (TAB_INTERVALS, TAB_HARMONIES)
T = TypeVar("T")
ChallengeSignature = tuple[int, tuple[tuple[int, int, int, int, int], ...]]
MAX_DISTINCT_CHALLENGE_ATTEMPTS = 50

TIMBRE_COLUMNS = 6
RANDOM_LABEL = "Random"
INTERVAL_MODES = ("Ascending", "Descending", "Harmonic")
PLAYABLE_PITCH_EDGE_MARGIN = 12
DURATION_LABELS = ("Short", "Medium", "Long")
DEFAULT_DURATION_LABEL = "Medium"
HARMONY_INVERSION_OPTIONS = (
    ("Root", 0),
    ("1st", 1),
    ("2nd", 2),
    ("3rd", 3),
)
DURATION_PROFILES = {
    "Short": {
        "melodic_note": 440,
        "melodic_step": 560,
        "simultaneous_note": 960,
        "harmony_chord": 1280,
        "progression_chord": 760,
        "progression_step": 920,
    },
    "Medium": {
        "melodic_note": 620,
        "melodic_step": 760,
        "simultaneous_note": 1320,
        "harmony_chord": 1700,
        "progression_chord": 1100,
        "progression_step": 1280,
    },
    "Long": {
        "melodic_note": 900,
        "melodic_step": 1080,
        "simultaneous_note": 1900,
        "harmony_chord": 2400,
        "progression_chord": 1600,
        "progression_step": 1850,
    },
}


class NoPlayableRangeError(RuntimeError):
    pass


def _weighted_choice_by_count(items: list[T], count_for: Callable[[T], int]) -> T:
    counts = [max(0, count_for(item)) for item in items]
    max_count = max(counts, default=0)
    weights = [max_count - count + 1 for count in counts]
    return random.choices(items, weights=weights, k=1)[0]


def _parse_enabled_tab_keys(raw_value: str) -> set[str]:
    aliases = {
        "interval": TAB_INTERVALS,
        "intervals": TAB_INTERVALS,
        "harmony": TAB_HARMONIES,
        "harmonies": TAB_HARMONIES,
        "progression": TAB_PROGRESSIONS,
        "progressions": TAB_PROGRESSIONS,
        "harmonic_functions": TAB_PROGRESSIONS,
        "harmonic-functions": TAB_PROGRESSIONS,
        "functions": TAB_PROGRESSIONS,
    }
    enabled_tabs: set[str] = set()
    for raw_part in raw_value.split(","):
        normalized = raw_part.strip().lower()
        if not normalized:
            continue
        tab_key = aliases.get(normalized)
        if tab_key is not None:
            enabled_tabs.add(tab_key)
    return enabled_tabs


@dataclass(frozen=True)
class Challenge:
    answer: str
    program: int
    notes: list[MidiNote]
    answer_notes: dict[str, list[MidiNote]]


class EarTrainerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Relative Ear Trainer")
        self.minsize(860, 620)

        try:
            instrument_definitions = load_instrument_definitions(INSTRUMENTS_PATH)
            interval_definitions = load_interval_definitions(INTERVALS_PATH)
            harmony_definitions = load_harmony_definitions(HARMONIES_PATH)
            progression_definitions = load_progression_definitions(
                PROGRESSIONS_PATH,
                harmony_definitions,
            )
        except ConfigError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            raise

        self.player = MidiPlayer()
        self.settings = SettingsStore()
        self.trainer_tabs: list[BaseTrainerTab] = []
        self._configure_style()

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook = notebook
        enabled_tab_keys = self._enabled_tab_keys()
        interval_tab = IntervalTrainerTab(
            notebook,
            self.player,
            self.settings,
            instrument_definitions,
            interval_definitions,
            self._stop_other_tabs,
        )
        harmony_tab = HarmonyTrainerTab(
            notebook,
            self.player,
            self.settings,
            instrument_definitions,
            harmony_definitions,
            self._stop_other_tabs,
        )
        progression_tab = ProgressionTrainerTab(
            notebook,
            self.player,
            self.settings,
            instrument_definitions,
            progression_definitions,
            self._stop_other_tabs,
        )
        available_tabs = {
            TAB_INTERVALS: (interval_tab, "Intervals"),
            TAB_HARMONIES: (harmony_tab, "Harmonies"),
            TAB_PROGRESSIONS: (progression_tab, "Harmonic Functions"),
        }
        self.trainer_tabs = [available_tabs[key][0] for key in enabled_tab_keys]

        for key in enabled_tab_keys:
            tab, label = available_tabs[key]
            notebook.add(tab, text=label)
        self.tab_keys = {
            str(tab): key
            for key, (tab, _label) in available_tabs.items()
            if key in enabled_tab_keys
        }

        active_tab_key = self.settings.option(
            "ui",
            "active_tab",
            list(self.tab_keys.values()),
            TAB_INTERVALS,
        )
        active_tab = next(
            (tab for tab in self.trainer_tabs if self.tab_keys[str(tab)] == active_tab_key),
            self.trainer_tabs[0],
        )
        notebook.select(active_tab)
        notebook.bind("<<NotebookTabChanged>>", self._save_active_tab)
        self.bind("<F7>", self._replay_active_tab)
        self.bind("<F8>", self._next_active_tab)

    def _enabled_tab_keys(self) -> tuple[str, ...]:
        enabled_from_env = os.environ.get(ENABLED_TABS_ENV_VAR)
        if enabled_from_env is not None:
            enabled_tab_keys = _parse_enabled_tab_keys(enabled_from_env)
        else:
            enabled_tab_keys = self.settings.selected_values(
                "features",
                "enabled_tabs",
                list(AVAILABLE_TAB_KEYS),
            )

        if not enabled_tab_keys:
            return DEFAULT_ENABLED_TAB_KEYS

        ordered_keys = tuple(key for key in AVAILABLE_TAB_KEYS if key in enabled_tab_keys)
        return ordered_keys or DEFAULT_ENABLED_TAB_KEYS

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.configure("Header.TLabel", font=("", 12, "bold"))
        style.configure("Result.TLabel", font=("", 12, "bold"))

    def _stop_other_tabs(self, active_tab: BaseTrainerTab) -> None:
        for tab in self.trainer_tabs:
            if tab is not active_tab and tab.running:
                tab.stop_training()

    def _save_active_tab(self, _event: tk.Event[ttk.Notebook]) -> None:
        active_tab = self.notebook.select()
        active_tab_key = self.tab_keys.get(active_tab)
        if active_tab_key is not None:
            self.settings.save_section("ui", {"active_tab": active_tab_key})

    def _active_trainer_tab(self) -> BaseTrainerTab | None:
        active_tab_name = self.notebook.select()
        return next(
            (tab for tab in self.trainer_tabs if str(tab) == active_tab_name),
            None,
        )

    def _replay_active_tab(self, _event: tk.Event[tk.Misc]) -> str:
        active_tab = self._active_trainer_tab()
        if active_tab is not None:
            active_tab.invoke_replay()
        return "break"

    def _next_active_tab(self, _event: tk.Event[tk.Misc]) -> str:
        active_tab = self._active_trainer_tab()
        if active_tab is not None:
            active_tab.invoke_next()
        return "break"


class BaseTrainerTab(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        settings_key: str,
        instruments: tuple[InstrumentDefinition, ...],
        definitions: tuple[MusicDefinition, ...],
        title: str,
        on_start: Callable[[BaseTrainerTab], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=12)
        self.player = player
        self.settings = settings
        self.settings_key = settings_key
        self.instruments = instruments
        self.instrument_names = [instrument.name for instrument in instruments]
        self.definitions = definitions
        self.title = title
        self.running = False
        self.current: Challenge | None = None
        self.current_marked_answer: str | None = None
        self.current_marked_correct: bool | None = None
        self.correct_count = 0
        self.total_count = 0
        self._last_challenge_signature: ChallengeSignature | None = None
        self._settings_save_after_id: str | None = None
        self.on_start = on_start

        selected_instruments = self.settings.selected_values(
            self.settings_key,
            "instruments",
            self.instrument_names,
        )
        if selected_instruments is None:
            legacy_instrument = self.settings.option(
                self.settings_key,
                "instrument",
                [*self.instrument_names, RANDOM_LABEL],
                RANDOM_LABEL,
            )
            selected_instruments = (
                set(self.instrument_names)
                if legacy_instrument == RANDOM_LABEL
                else {legacy_instrument}
            )
        self.instrument_vars = {
            name: tk.BooleanVar(value=name in selected_instruments)
            for name in self.instrument_names
        }
        self.duration_var = tk.StringVar(
            value=self.settings.option(
                self.settings_key,
                "duration",
                list(DURATION_LABELS),
                DEFAULT_DURATION_LABEL,
            )
        )
        self.status_var = tk.StringVar(value=f"MIDI: {self.player.describe_backend()}")
        self.feedback_var = tk.StringVar(value="")
        self.score_var = tk.StringVar(value=self._score_text())
        selected_names = self.settings.selected_names(
            self.settings_key,
            [definition.name for definition in self.definitions],
        )
        self.selection_vars = {}
        for definition in self.definitions:
            selected = True if selected_names is None else definition.name in selected_names
            self.selection_vars[definition.name] = tk.BooleanVar(value=selected)
        self.answer_buttons: dict[str, ttk.Button] = {}
        self.answer_stats = self.settings.stats(self.settings_key)
        self.challenge_counts: dict[str, int] = {}
        self._instrument_pitch_cache: dict[str, set[int]] = {}
        self.selection_controls: list[tk.Widget] = []
        self.definition_checkbuttons: list[ttk.Checkbutton] = []
        self.definition_grid_parent: ttk.Frame | None = None
        self.definition_canvas: tk.Canvas | None = None
        self._definition_grid_columns = 0

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._build_header()
        self._build_definition_selector()
        self._build_answer_area()
        self._build_controls()
        self._sync_answer_buttons_with_selection()
        self._set_answer_buttons_enabled(False)
        self._bind_selection_persistence()

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
        self._build_instrument_selector(timbre_frame)

        duration_frame = ttk.LabelFrame(header, text="Duration", padding=8)
        duration_frame.grid(row=1, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(DURATION_LABELS):
            ttk.Radiobutton(
                duration_frame,
                text=label,
                value=label,
                variable=self.duration_var,
            ).grid(row=0, column=column, padx=4)

    def _build_instrument_selector(self, parent: tk.Widget) -> None:
        for index, label in enumerate(self.instrument_names):
            row, column = divmod(index, TIMBRE_COLUMNS)
            checkbutton = ttk.Checkbutton(
                parent,
                text=label,
                variable=self.instrument_vars[label],
            )
            checkbutton.grid(row=row, column=column, padx=4, sticky="w")
            self.selection_controls.append(checkbutton)

    def _build_definition_selector(self) -> None:
        outer = ttk.LabelFrame(self, text="Selection", padding=8)
        outer.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)

        buttons = ttk.Frame(outer)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        all_button = ttk.Button(buttons, text="All", command=lambda: self._set_all_selections(True))
        all_button.pack(side=tk.LEFT)
        none_button = ttk.Button(
            buttons,
            text="None",
            command=lambda: self._set_all_selections(False),
        )
        none_button.pack(side=tk.LEFT, padx=(6, 0))
        self.selection_controls.extend([all_button, none_button])

        definition_columns = self._definition_columns_for_width(0)
        selector_height = self._selector_height(definition_columns)
        grid_parent, canvas = self._scrollable_frame(
            outer,
            height=selector_height,
            expand=False,
        )
        self.definition_grid_parent = grid_parent
        self.definition_canvas = canvas
        for definition in self.definitions:
            checkbutton = ttk.Checkbutton(
                grid_parent,
                text=self._definition_selection_label(definition),
                variable=self.selection_vars[definition.name],
            )
            self.definition_checkbuttons.append(checkbutton)
            self.selection_controls.append(checkbutton)
        self._layout_definition_selector(definition_columns)
        canvas.bind("<Configure>", self._reflow_definition_selector, add="+")

    def _definition_selection_label(self, definition: MusicDefinition) -> str:
        return definition.name

    def _build_answer_area(self) -> None:
        outer = ttk.LabelFrame(self, text="Answer", padding=8)
        outer.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        grid_parent = ttk.Frame(outer)
        grid_parent.grid(row=0, column=0, sticky="new")
        self.answer_grid_parent = grid_parent
        for definition in self.definitions:
            button = ttk.Button(
                grid_parent,
                text=self._answer_button_text(definition.name),
                command=lambda name=definition.name: self._answer(name),
            )
            self.answer_buttons[definition.name] = button

    def _definition_columns(self, definitions: list[MusicDefinition] | None = None) -> int:
        definitions = definitions or list(self.definitions)
        max_name_length = max(
            (len(self._definition_selection_label(definition)) for definition in definitions),
            default=0,
        )
        if max_name_length > 18:
            return 2
        if len(definitions) > 24:
            return 8
        return 6

    def _definition_columns_for_width(self, width: int) -> int:
        if not self.definitions:
            return 1

        max_columns = min(len(self.definitions), 8)
        if width <= 1:
            return min(max_columns, 6)

        column_width = self._definition_column_width()
        available_width = max(width - 20, column_width)
        return max(1, min(max_columns, available_width // column_width))

    def _definition_column_width(self) -> int:
        max_name_length = max(
            (len(self._definition_selection_label(definition)) for definition in self.definitions),
            default=0,
        )
        return max(96, min(280, (max_name_length * 8) + 44))

    def _selector_height(self, definition_columns: int) -> int:
        definition_rows = max(
            1,
            (len(self.definitions) + definition_columns - 1) // definition_columns,
        )
        return min(definition_rows, 6) * 30 + 2

    def _layout_definition_selector(self, definition_columns: int) -> None:
        if self.definition_grid_parent is None:
            return

        columns_to_reset = max(8, self._definition_grid_columns, definition_columns)
        for column in range(columns_to_reset):
            self.definition_grid_parent.columnconfigure(column, weight=0, minsize=0)

        for checkbutton in self.definition_checkbuttons:
            checkbutton.grid_forget()

        for index, checkbutton in enumerate(self.definition_checkbuttons):
            row, column = divmod(index, definition_columns)
            checkbutton.grid(row=row, column=column, sticky="w", padx=8, pady=3)
            self.definition_grid_parent.columnconfigure(column, weight=1)

        self._definition_grid_columns = definition_columns
        if self.definition_canvas is not None:
            selector_height = self._selector_height(definition_columns)
            if int(self.definition_canvas.cget("height")) != selector_height:
                self.definition_canvas.configure(height=selector_height)

    def _reflow_definition_selector(self, event: tk.Event[tk.Canvas]) -> None:
        definition_columns = self._definition_columns_for_width(event.width)
        if definition_columns != self._definition_grid_columns:
            self._layout_definition_selector(definition_columns)

    def _build_controls(self) -> None:
        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(footer, text="Start", command=self._toggle_running)
        self.start_button.grid(row=0, column=0, padx=(0, 6))
        self.replay_button = ttk.Button(
            footer,
            text="Replay (F7)",
            command=self._replay_current,
            state=tk.DISABLED,
        )
        self.replay_button.grid(row=0, column=1, padx=(0, 6))
        self.next_button = ttk.Button(
            footer,
            text="Next (F8)",
            command=self._next_challenge,
            state=tk.DISABLED,
        )
        self.next_button.grid(row=0, column=2, padx=(0, 6))
        self.reset_stats_button = ttk.Button(
            footer,
            text="Reset Stats",
            command=self._reset_stats,
        )
        self.reset_stats_button.grid(row=0, column=5, padx=(10, 0), sticky="e")
        ttk.Label(footer, textvariable=self.status_var, style="Result.TLabel").grid(
            row=0,
            column=3,
            sticky="w",
            padx=(4, 10),
        )
        ttk.Label(footer, textvariable=self.score_var).grid(row=0, column=4, sticky="e")
        ttk.Label(footer, textvariable=self.feedback_var, style="Result.TLabel").grid(
            row=1,
            column=0,
            columnspan=6,
            sticky="w",
            pady=(6, 0),
        )

    def _scrollable_frame(
        self,
        parent: tk.Widget,
        height: int,
        expand: bool = True,
    ) -> tuple[ttk.Frame, tk.Canvas]:
        container = ttk.Frame(parent)
        _columns, next_row = parent.grid_size()
        container.grid(row=next_row, column=0, sticky="nsew" if expand else "ew")
        container.columnconfigure(0, weight=1)
        if expand:
            container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, height=height, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew" if expand else "ew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        def update_scroll_region(_event: tk.Event[tk.Widget]) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event: tk.Event[tk.Widget]) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)
        return inner, canvas

    def _set_all_selections(self, selected: bool) -> None:
        for variable in self.selection_vars.values():
            variable.set(selected)

    def _bind_selection_persistence(self) -> None:
        for variable in self.selection_vars.values():
            variable.trace_add("write", lambda *_args: self._queue_settings_save())
        for variable in self.instrument_vars.values():
            variable.trace_add("write", lambda *_args: self._queue_settings_save())
        self.duration_var.trace_add("write", lambda *_args: self._queue_settings_save())

    def _queue_settings_save(self) -> None:
        self._sync_answer_buttons_with_selection()
        if self._settings_save_after_id is not None:
            self.after_cancel(self._settings_save_after_id)
        self._settings_save_after_id = self.after(250, self._save_settings)

    def _save_settings(self) -> None:
        self._settings_save_after_id = None
        selected_names = [
            definition.name
            for definition in self.definitions
            if self.selection_vars[definition.name].get()
        ]
        payload = {
            "selected": selected_names,
            "instruments": [
                name for name in self.instrument_names if self.instrument_vars[name].get()
            ],
            "duration": self.duration_var.get(),
        }
        payload.update(self._extra_settings_payload())
        try:
            self.settings.save_section(self.settings_key, payload)
        except OSError as exc:
            self.status_var.set(f"Could not save settings: {exc}")

    def _extra_settings_payload(self) -> dict[str, str | bool | list[str]]:
        return {}

    def _active_definitions(self) -> list[MusicDefinition]:
        return [
            definition
            for definition in self.definitions
            if self.selection_vars[definition.name].get()
        ]

    def _active_instruments(self) -> list[InstrumentDefinition]:
        return [
            instrument
            for instrument in self.instruments
            if self.instrument_vars[instrument.name].get()
        ]

    def _sync_answer_buttons_with_selection(self) -> None:
        active_definitions = self._active_definitions()
        active_names = {definition.name for definition in active_definitions}
        definition_columns = self._definition_columns(active_definitions)

        for column in range(max(8, definition_columns)):
            self.answer_grid_parent.columnconfigure(column, weight=0, minsize=0)

        for button in self.answer_buttons.values():
            button.grid_remove()

        for index, definition in enumerate(active_definitions):
            row, column = divmod(index, definition_columns)
            button = self.answer_buttons[definition.name]
            button.configure(text=self._answer_button_text(definition.name))
            button.grid(row=row, column=column, sticky="ew", padx=5, pady=4)
            self.answer_grid_parent.columnconfigure(column, weight=1, minsize=100)

        if self.running and self.current is not None and self.current.answer not in active_names:
            self._set_answer_buttons_enabled(False)
            self.status_var.set("Current answer was removed from selection")

    def _toggle_running(self) -> None:
        if self.running:
            self.stop_training()
        else:
            self._start()

    def invoke_replay(self) -> None:
        self.replay_button.invoke()

    def invoke_next(self) -> None:
        self.next_button.invoke()

    def _start(self) -> None:
        if not self._active_definitions():
            self.status_var.set("Select at least one option")
            return
        if not self._active_instruments():
            self.status_var.set("Select at least one instrument")
            return

        if self.on_start is not None:
            self.on_start(self)
        self._save_settings()
        self.running = True
        self.challenge_counts = self._initial_challenge_counts()
        self._last_challenge_signature = None
        self.correct_count = 0
        self.total_count = 0
        self.feedback_var.set("")
        self.score_var.set(self._score_text())
        self.start_button.configure(text="Stop")
        self.replay_button.configure(state=tk.NORMAL)
        self.next_button.configure(state=tk.DISABLED)
        self._set_selection_controls_enabled(False)
        self._next_challenge()

    def stop_training(self) -> None:
        self.player.stop()
        self.running = False
        self.current = None
        self.current_marked_answer = None
        self.current_marked_correct = None
        self._last_challenge_signature = None
        self.start_button.configure(text="Start")
        self.replay_button.configure(state=tk.DISABLED)
        self.next_button.configure(state=tk.DISABLED)
        self._set_answer_buttons_enabled(False)
        self._set_selection_controls_enabled(True)
        self.status_var.set("Stopped")

    def _next_challenge(self) -> None:
        self.player.stop()
        if not self.running:
            return

        active_definitions = self._active_definitions()
        if not active_definitions:
            self.stop_training()
            self.status_var.set("Select at least one option")
            return

        try:
            self.current = self._build_next_distinct_challenge(active_definitions)
        except NoPlayableRangeError as exc:
            self.stop_training()
            self.status_var.set(str(exc))
            return
        self._last_challenge_signature = self._challenge_signature(self.current)
        self._record_challenge(self.current.answer)
        self.current_marked_answer = None
        self.current_marked_correct = None
        self._set_answer_buttons_enabled(True)
        self.next_button.configure(state=tk.DISABLED)
        self.feedback_var.set("")
        self.status_var.set("Listen")
        self._play_current()

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        raise NotImplementedError

    def _build_next_distinct_challenge(
        self,
        active_definitions: list[MusicDefinition],
    ) -> Challenge:
        fallback: Challenge | None = None
        last_signature = self._last_challenge_signature

        for _attempt in range(MAX_DISTINCT_CHALLENGE_ATTEMPTS):
            definition = self._choose_definition(active_definitions)
            challenge = self._build_challenge(definition)
            if last_signature is None:
                return challenge
            if fallback is None:
                fallback = challenge
            if self._challenge_signature(challenge) != last_signature:
                return challenge

        if fallback is None:
            raise NoPlayableRangeError(
                "No selected instrument can play every note in the current selection"
            )
        return fallback

    def _challenge_signature(self, challenge: Challenge) -> ChallengeSignature:
        note_events = tuple(
            sorted(
                (
                    note.start,
                    note.duration,
                    note.pitch,
                    note.velocity,
                    -1 if note.program is None else note.program,
                )
                for note in challenge.notes
            )
        )
        return (challenge.program, note_events)

    def _choose_definition(self, definitions: list[MusicDefinition]) -> MusicDefinition:
        return _weighted_choice_by_count(definitions, self._definition_challenge_count)

    def _definition_challenge_count(self, definition: MusicDefinition) -> int:
        return self._answer_challenge_count(definition.name)

    def _initial_challenge_counts(self) -> dict[str, int]:
        return {answer: 0 for answer in self._active_balance_answer_names()}

    def _active_balance_answer_names(self) -> list[str]:
        return [definition.name for definition in self._active_definitions()]

    def _answer_challenge_count(self, answer: str) -> int:
        return self.challenge_counts.get(answer, 0)

    def _record_challenge(self, answer: str) -> None:
        self.challenge_counts[answer] = self._answer_challenge_count(answer) + 1

    def _choose_instrument_and_root(
        self,
        offsets: Iterable[int],
    ) -> tuple[InstrumentDefinition, int]:
        active_instruments = self._active_instruments()
        random.shuffle(active_instruments)
        offset_values = tuple(offsets) or (0,)
        for instrument in active_instruments:
            root = self._choose_root_for_offsets(instrument, offset_values)
            if root is not None:
                return instrument, root

        raise NoPlayableRangeError(
            "No selected instrument can play every note in the current selection"
        )

    def _choose_root_for_offsets(
        self,
        instrument: InstrumentDefinition,
        offsets: Iterable[int],
    ) -> int | None:
        offset_values = tuple(offsets) or (0,)
        playable_pitches = self._playable_pitches_for_instrument(instrument)
        if not playable_pitches:
            return None

        low_note = min(playable_pitches)
        high_note = max(playable_pitches)
        min_offset = min(offset_values)
        max_offset = max(offset_values)
        min_root = max(0, low_note - min_offset)
        max_root = min(127, high_note - max_offset)

        if min_root <= max_root:
            pitch_class = random.randrange(12)
            candidates = [
                root
                for root in range(min_root, max_root + 1)
                if root % 12 == pitch_class
                and all(root + offset in playable_pitches for offset in offset_values)
            ]
            if candidates:
                return random.choice(candidates)
            candidates = [
                root
                for root in range(min_root, max_root + 1)
                if all(root + offset in playable_pitches for offset in offset_values)
            ]
            if candidates:
                return random.choice(candidates)

        return None

    def _playable_pitches_for_instrument(self, instrument: InstrumentDefinition) -> set[int]:
        cached_pitches = self._instrument_pitch_cache.get(instrument.name)
        if cached_pitches is not None:
            return cached_pitches

        configured_pitches = set(range(instrument.low_note, instrument.high_note + 1))
        backend_key = self.player.audibility_cache_key()
        if backend_key is None:
            effective_pitches = self._effective_pitch_set(configured_pitches)
            self._instrument_pitch_cache[instrument.name] = effective_pitches
            return effective_pitches

        stored_pitches = self.settings.audible_pitches(
            backend_key=backend_key,
            instrument_name=instrument.name,
            program=instrument.program,
            low_note=instrument.low_note,
            high_note=instrument.high_note,
        )
        if stored_pitches is not None:
            effective_pitches = self._effective_pitch_set(stored_pitches)
            self._instrument_pitch_cache[instrument.name] = effective_pitches
            return effective_pitches

        self.status_var.set(f"Checking {instrument.name} MIDI range")
        self.update_idletasks()
        measured_pitches = self.player.measure_audible_pitches(
            program=instrument.program,
            pitches=sorted(configured_pitches),
        )
        if measured_pitches is None:
            effective_pitches = self._effective_pitch_set(configured_pitches)
            self._instrument_pitch_cache[instrument.name] = effective_pitches
            return effective_pitches

        try:
            self.settings.save_audible_pitches(
                backend_key=backend_key,
                instrument_name=instrument.name,
                program=instrument.program,
                low_note=instrument.low_note,
                high_note=instrument.high_note,
                pitches=measured_pitches,
            )
        except OSError as exc:
            self.status_var.set(f"Could not save MIDI range: {exc}")
        effective_pitches = self._effective_pitch_set(measured_pitches)
        self._instrument_pitch_cache[instrument.name] = effective_pitches
        return effective_pitches

    def _effective_pitch_set(self, pitches: set[int]) -> set[int]:
        if not pitches:
            return set()

        low_note = min(pitches) + PLAYABLE_PITCH_EDGE_MARGIN
        high_note = max(pitches) - PLAYABLE_PITCH_EDGE_MARGIN
        if low_note > high_note:
            return set()
        return {pitch for pitch in pitches if low_note <= pitch <= high_note}

    def _duration_profile(self) -> dict[str, int]:
        return DURATION_PROFILES.get(
            self.duration_var.get(),
            DURATION_PROFILES[DEFAULT_DURATION_LABEL],
        )

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
        if correct:
            feedback = f"Correct: {self.current.answer}"
        else:
            feedback = f"Selected: {answer}; correct answer: {self.current.answer}"

        stats_error = self._apply_answer_result(
            self.current.answer,
            self.current_marked_correct,
            correct,
        )
        self.current_marked_answer = answer
        self.current_marked_correct = correct
        self.feedback_var.set(feedback)
        self.status_var.set(stats_error or "Review the answer")
        self.score_var.set(self._score_text())
        self.next_button.configure(state=tk.NORMAL)
        self._play_answer(answer)

    def _score_text(self) -> str:
        if self.total_count == 0:
            return "Correct: 0/0 (0%)"
        percentage = round((self.correct_count / self.total_count) * 100)
        return f"Correct: {self.correct_count}/{self.total_count} ({percentage}%)"

    def _play_answer(self, answer: str) -> None:
        if self.current is None:
            return
        notes = self.current.answer_notes.get(answer)
        if not notes:
            return
        try:
            self.player.play(program=self.current.program, notes=notes)
        except PlaybackError as exc:
            self.status_var.set(str(exc))

    def _apply_answer_result(
        self,
        answer: str,
        previous_correct: bool | None,
        correct: bool,
    ) -> str | None:
        attempts_delta = 0
        correct_delta = 0
        if previous_correct is None:
            self.total_count += 1
            attempts_delta = 1
            if correct:
                self.correct_count += 1
                correct_delta = 1
        elif previous_correct != correct:
            correct_delta = 1 if correct else -1
            self.correct_count += correct_delta

        if attempts_delta == 0 and correct_delta == 0:
            return None

        answer_stats = self.answer_stats.setdefault(answer, {"correct": 0, "attempts": 0})
        answer_stats["attempts"] += attempts_delta
        answer_stats["correct"] += correct_delta
        answer_stats["correct"] = max(
            0,
            min(answer_stats["correct"], answer_stats["attempts"]),
        )
        error: str | None = None
        try:
            self.settings.save_stats(self.settings_key, self.answer_stats)
        except OSError as exc:
            error = f"Could not save stats: {exc}"
        self._refresh_answer_button_texts()
        return error

    def _reset_stats(self) -> None:
        if not messagebox.askyesno("Reset stats", f"Reset stats for {self.title}?"):
            return

        self.answer_stats = {}
        self.challenge_counts = {}
        try:
            self.settings.reset_stats(self.settings_key)
        except OSError as exc:
            self.status_var.set(f"Could not reset stats: {exc}")
            return
        self._refresh_answer_button_texts()
        self.status_var.set("Stats reset")

    def _refresh_answer_button_texts(self) -> None:
        for answer, button in self.answer_buttons.items():
            button.configure(text=self._answer_button_text(answer))

    def _answer_button_text(self, answer: str) -> str:
        return f"{answer}  {self._answer_stat_label(answer)}"

    def _answer_stat_label(self, answer: str) -> str:
        answer_stats = self.answer_stats.get(answer, {})
        attempts = int(answer_stats.get("attempts", 0))
        correct = int(answer_stats.get("correct", 0))
        if attempts == 0:
            return "--% (0/0)"
        percentage = round((correct / attempts) * 100)
        return f"{percentage}% ({correct}/{attempts})"

    def _set_answer_buttons_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for button in self.answer_buttons.values():
            button.configure(state=state)

    def _set_selection_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for control in self.selection_controls:
            control.configure(state=state)


class IntervalTrainerTab(BaseTrainerTab):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        instruments: tuple[InstrumentDefinition, ...],
        definitions: tuple[MusicDefinition, ...],
        on_start: Callable[[BaseTrainerTab], None] | None,
    ) -> None:
        selected_modes = settings.selected_values(
            "intervals",
            "modes",
            list(INTERVAL_MODES),
        )
        if selected_modes is None:
            legacy_mode = settings.option(
                "intervals",
                "mode",
                [*INTERVAL_MODES, RANDOM_LABEL],
                RANDOM_LABEL,
            )
            selected_modes = (
                set(INTERVAL_MODES) if legacy_mode == RANDOM_LABEL else {legacy_mode}
            )
        self.interval_mode_vars = {
            mode: tk.BooleanVar(master=parent, value=mode in selected_modes)
            for mode in INTERVAL_MODES
        }
        self.mix_instruments_var = tk.BooleanVar(
            master=parent,
            value=settings.boolean_option("intervals", "mix_instruments", False),
        )
        super().__init__(
            parent,
            player,
            settings,
            "intervals",
            instruments,
            definitions,
            title="Interval training",
            on_start=on_start,
        )

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=self.title, style="Header.TLabel").grid(
            row=0,
            column=0,
            rowspan=3,
            sticky="w",
        )

        timbre_frame = ttk.LabelFrame(header, text="Instrument", padding=8)
        timbre_frame.grid(row=0, column=1, sticky="e")
        self._build_instrument_selector(timbre_frame)
        mix_row = (len(self.instrument_names) + TIMBRE_COLUMNS - 1) // TIMBRE_COLUMNS
        mix_checkbutton = ttk.Checkbutton(
            timbre_frame,
            text="Mix",
            variable=self.mix_instruments_var,
        )
        mix_checkbutton.grid(row=mix_row, column=0, padx=4, pady=(6, 0), sticky="w")
        self.selection_controls.append(mix_checkbutton)

        mode_frame = ttk.LabelFrame(header, text="Mode", padding=8)
        mode_frame.grid(row=1, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(INTERVAL_MODES):
            checkbutton = ttk.Checkbutton(
                mode_frame,
                text=label,
                variable=self.interval_mode_vars[label],
            )
            checkbutton.grid(row=0, column=column, padx=4)
            self.selection_controls.append(checkbutton)

        duration_frame = ttk.LabelFrame(header, text="Duration", padding=8)
        duration_frame.grid(row=2, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(DURATION_LABELS):
            ttk.Radiobutton(
                duration_frame,
                text=label,
                value=label,
                variable=self.duration_var,
            ).grid(row=0, column=column, padx=4)

    def _bind_selection_persistence(self) -> None:
        super()._bind_selection_persistence()
        for variable in self.interval_mode_vars.values():
            variable.trace_add("write", lambda *_args: self._queue_settings_save())
        self.mix_instruments_var.trace_add(
            "write",
            lambda *_args: self._queue_settings_save(),
        )

    def _extra_settings_payload(self) -> dict[str, str | bool | list[str]]:
        return {
            "modes": self._active_interval_modes(),
            "mix_instruments": self.mix_instruments_var.get(),
        }

    def _active_interval_modes(self) -> list[str]:
        return [mode for mode in INTERVAL_MODES if self.interval_mode_vars[mode].get()]

    def _start(self) -> None:
        if not self._active_interval_modes():
            self.status_var.set("Select at least one mode")
            return
        super()._start()

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        mode = random.choice(self._active_interval_modes())

        timing = self._duration_profile()
        active_definitions = self._active_definitions()
        intervals = [
            active_definition.semitones[0] for active_definition in active_definitions
        ]
        if self.mix_instruments_var.get():
            low_instrument, high_instrument, root = (
                self._choose_interval_instruments_and_root(intervals, mode)
            )
        else:
            direction = -1 if mode == "Descending" else 1
            offsets = [0, *(direction * interval for interval in intervals)]
            instrument, root = self._choose_instrument_and_root(offsets)
            low_instrument = high_instrument = instrument
        answer_notes = {
            active_definition.name: self._build_interval_notes(
                interval=active_definition.semitones[0],
                mode=mode,
                root=root,
                timing=timing,
                low_program=low_instrument.program,
                high_program=high_instrument.program,
            )
            for active_definition in active_definitions
        }
        return Challenge(
            answer=definition.name,
            program=low_instrument.program,
            notes=answer_notes[definition.name],
            answer_notes=answer_notes,
        )

    def _choose_interval_instruments_and_root(
        self,
        intervals: Iterable[int],
        mode: str,
    ) -> tuple[InstrumentDefinition, InstrumentDefinition, int]:
        instruments = self._active_instruments()
        interval_values = tuple(abs(interval) for interval in intervals) or (0,)
        distinct_pairs = [
            (low_instrument, high_instrument)
            for low_instrument in instruments
            for high_instrument in instruments
            if low_instrument != high_instrument
        ]
        same_pairs = [(instrument, instrument) for instrument in instruments]
        random.shuffle(distinct_pairs)
        random.shuffle(same_pairs)

        for low_instrument, high_instrument in [*distinct_pairs, *same_pairs]:
            low_pitches = self._playable_pitches_for_instrument(low_instrument)
            high_pitches = self._playable_pitches_for_instrument(high_instrument)
            if mode == "Descending":
                candidates = [
                    root
                    for root in high_pitches
                    if all(root - interval in low_pitches for interval in interval_values)
                ]
            else:
                candidates = [
                    root
                    for root in low_pitches
                    if all(root + interval in high_pitches for interval in interval_values)
                ]
            if not candidates:
                continue

            pitch_class = random.choice(sorted({root % 12 for root in candidates}))
            roots = [root for root in candidates if root % 12 == pitch_class]
            return low_instrument, high_instrument, random.choice(roots)

        raise NoPlayableRangeError(
            "No selected instrument pair can play every note in the current selection"
        )

    def _build_interval_notes(
        self,
        interval: int,
        mode: str,
        root: int,
        timing: dict[str, int],
        low_program: int,
        high_program: int,
    ) -> list[MidiNote]:
        if mode == "Ascending":
            return [
                MidiNote(
                    start=0,
                    duration=timing["melodic_note"],
                    pitch=root,
                    program=low_program,
                ),
                MidiNote(
                    start=timing["melodic_step"],
                    duration=timing["melodic_note"],
                    pitch=root + interval,
                    program=high_program,
                ),
            ]
        if mode == "Descending":
            return [
                MidiNote(
                    start=0,
                    duration=timing["melodic_note"],
                    pitch=root,
                    program=high_program,
                ),
                MidiNote(
                    start=timing["melodic_step"],
                    duration=timing["melodic_note"],
                    pitch=root - interval,
                    program=low_program,
                ),
            ]

        notes = [
            MidiNote(
                start=0,
                duration=timing["simultaneous_note"],
                pitch=root,
                program=low_program,
            )
        ]
        target = root + interval
        if target != root:
            notes.append(
                MidiNote(
                    start=0,
                    duration=timing["simultaneous_note"],
                    pitch=target,
                    program=high_program,
                )
            )
        return notes


class HarmonyTrainerTab(BaseTrainerTab):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        instruments: tuple[InstrumentDefinition, ...],
        definitions: tuple[MusicDefinition, ...],
        on_start: Callable[[BaseTrainerTab], None] | None,
    ) -> None:
        selected_modes = settings.selected_values(
            "harmonies",
            "modes",
            list(INTERVAL_MODES),
        )
        if selected_modes is None:
            legacy_mode = settings.option(
                "harmonies",
                "mode",
                [*INTERVAL_MODES, RANDOM_LABEL],
                "Harmonic",
            )
            selected_modes = (
                set(INTERVAL_MODES) if legacy_mode == RANDOM_LABEL else {legacy_mode}
            )
        self.harmony_mode_vars = {
            mode: tk.BooleanVar(master=parent, value=mode in selected_modes)
            for mode in INTERVAL_MODES
        }
        self.mix_instruments_var = tk.BooleanVar(
            master=parent,
            value=settings.boolean_option("harmonies", "mix_instruments", False),
        )
        inversion_labels = [label for label, _degree in HARMONY_INVERSION_OPTIONS]
        selected_inversions = settings.selected_values(
            "harmonies",
            "inversions",
            inversion_labels,
        )
        self.inversion_vars = {
            label: tk.BooleanVar(
                master=parent,
                value=label in selected_inversions
                if selected_inversions is not None
                else degree == 0,
            )
            for label, degree in HARMONY_INVERSION_OPTIONS
        }
        super().__init__(
            parent,
            player,
            settings,
            "harmonies",
            instruments,
            definitions,
            title="Harmony training",
            on_start=on_start,
        )

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=self.title, style="Header.TLabel").grid(
            row=0,
            column=0,
            rowspan=4,
            sticky="w",
        )
        timbre_frame = ttk.LabelFrame(header, text="Instrument", padding=8)
        timbre_frame.grid(row=0, column=1, sticky="e")
        self._build_instrument_selector(timbre_frame)
        mix_row = (len(self.instrument_names) + TIMBRE_COLUMNS - 1) // TIMBRE_COLUMNS
        mix_checkbutton = ttk.Checkbutton(
            timbre_frame,
            text="Mix",
            variable=self.mix_instruments_var,
        )
        mix_checkbutton.grid(row=mix_row, column=0, padx=4, pady=(6, 0), sticky="w")
        self.selection_controls.append(mix_checkbutton)

        mode_frame = ttk.LabelFrame(header, text="Mode", padding=8)
        mode_frame.grid(row=1, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(INTERVAL_MODES):
            checkbutton = ttk.Checkbutton(
                mode_frame,
                text=label,
                variable=self.harmony_mode_vars[label],
            )
            checkbutton.grid(row=0, column=column, padx=4)
            self.selection_controls.append(checkbutton)

        inversion_frame = ttk.LabelFrame(header, text="Inversions", padding=8)
        inversion_frame.grid(row=2, column=1, sticky="e", pady=(6, 0))
        for column, (label, _degree) in enumerate(HARMONY_INVERSION_OPTIONS):
            checkbutton = ttk.Checkbutton(
                inversion_frame,
                text=label,
                variable=self.inversion_vars[label],
            )
            checkbutton.grid(row=0, column=column, padx=4)
            self.selection_controls.append(checkbutton)

        duration_frame = ttk.LabelFrame(header, text="Duration", padding=8)
        duration_frame.grid(row=3, column=1, sticky="e", pady=(6, 0))
        for column, label in enumerate(DURATION_LABELS):
            ttk.Radiobutton(
                duration_frame,
                text=label,
                value=label,
                variable=self.duration_var,
            ).grid(row=0, column=column, padx=4)

    def _definition_selection_label(self, definition: MusicDefinition) -> str:
        return f"{definition.name} ({', '.join(definition.formula)})"

    def _build_answer_area(self) -> None:
        outer = ttk.LabelFrame(self, text="Answer", padding=8)
        outer.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        grid_parent = ttk.Frame(outer)
        grid_parent.grid(row=0, column=0, sticky="new")
        self.answer_grid_parent = grid_parent
        for definition in self.definitions:
            for inversion in range(min(3, len(definition.semitones) - 1) + 1):
                answer_name = self._answer_name(definition, inversion)
                button = ttk.Button(
                    grid_parent,
                    text=self._answer_button_text(answer_name),
                    command=lambda name=answer_name: self._answer(name),
                )
                self.answer_buttons[answer_name] = button

    def _bind_selection_persistence(self) -> None:
        super()._bind_selection_persistence()
        for variable in self.harmony_mode_vars.values():
            variable.trace_add("write", lambda *_args: self._queue_settings_save())
        for variable in self.inversion_vars.values():
            variable.trace_add(
                "write",
                lambda *_args: self._queue_settings_save(),
            )
        self.mix_instruments_var.trace_add(
            "write",
            lambda *_args: self._queue_settings_save(),
        )

    def _extra_settings_payload(self) -> dict[str, str | bool | list[str]]:
        selected_inversions = [
            label
            for label, _degree in HARMONY_INVERSION_OPTIONS
            if self.inversion_vars[label].get()
        ]
        return {
            "modes": self._active_harmony_modes(),
            "inversions": selected_inversions,
            "mix_instruments": self.mix_instruments_var.get(),
        }

    def _active_harmony_modes(self) -> list[str]:
        return [mode for mode in INTERVAL_MODES if self.harmony_mode_vars[mode].get()]

    def _start(self) -> None:
        if not self._active_harmony_modes():
            self.status_var.set("Select at least one mode")
            return
        super()._start()

    def _sync_answer_buttons_with_selection(self) -> None:
        active_answers = self._active_answer_names()
        active_answer_set = set(active_answers)
        answer_columns = self._answer_columns(active_answers)

        for column in range(max(8, answer_columns)):
            self.answer_grid_parent.columnconfigure(column, weight=0, minsize=0)

        for button in self.answer_buttons.values():
            button.grid_remove()

        for index, answer_name in enumerate(active_answers):
            row, column = divmod(index, answer_columns)
            button = self.answer_buttons[answer_name]
            button.configure(text=self._answer_button_text(answer_name))
            button.grid(row=row, column=column, sticky="ew", padx=5, pady=4)
            self.answer_grid_parent.columnconfigure(column, weight=1, minsize=125)

        if self.running and self.current is not None and self.current.answer not in active_answer_set:
            self._set_answer_buttons_enabled(False)
            self.status_var.set("Current answer was removed from selection")

    def _build_challenge(self, definition: MusicDefinition) -> Challenge:
        timing = self._duration_profile()
        active_definitions = self._active_definitions()
        if self.mix_instruments_var.get():
            voice_instruments, root = self._choose_harmony_instruments_and_root(
                active_definitions
            )
            program = voice_instruments[0].program
            voice_programs = [instrument.program for instrument in voice_instruments]
        else:
            instrument, root = self._choose_instrument_and_root(
                self._harmony_answer_offsets(active_definitions)
            )
            program = instrument.program
            voice_programs = None
        inversion = self._choose_inversion(definition)
        mode = self._actual_harmony_mode()
        answer_notes = self._build_harmony_answer_notes(
            root=root,
            timing=timing,
            mode=mode,
            active_definitions=active_definitions,
            voice_programs=voice_programs,
        )
        answer = self._answer_name(definition, inversion)
        return Challenge(
            answer=answer,
            program=program,
            notes=answer_notes[answer],
            answer_notes=answer_notes,
        )

    def _choose_harmony_instruments_and_root(
        self,
        active_definitions: list[MusicDefinition],
    ) -> tuple[list[InstrumentDefinition], int]:
        offset_sets = [
            self._apply_inversion(definition.semitones, inversion)
            for definition in active_definitions
            for inversion in self._active_inversions(len(definition.semitones))
        ]
        voice_count = max((len(offsets) for offsets in offset_sets), default=0)
        if voice_count == 0:
            raise NoPlayableRangeError("No selected harmony has playable voices")

        offsets_by_voice = [
            {
                offsets[voice_index]
                for offsets in offset_sets
                if voice_index < len(offsets)
            }
            for voice_index in range(voice_count)
        ]
        instruments = self._active_instruments()
        playable_by_instrument = {
            instrument.name: self._playable_pitches_for_instrument(instrument)
            for instrument in instruments
        }
        candidates: list[tuple[int, list[list[InstrumentDefinition]]]] = []
        for root in range(128):
            eligible_by_voice = [
                [
                    instrument
                    for instrument in instruments
                    if all(
                        root + offset in playable_by_instrument[instrument.name]
                        for offset in voice_offsets
                    )
                ]
                for voice_offsets in offsets_by_voice
            ]
            if all(eligible_by_voice):
                candidates.append((root, eligible_by_voice))

        if not candidates:
            raise NoPlayableRangeError(
                "No selected instrument mix can play every note in the current selection"
            )

        pitch_class = random.choice(sorted({root % 12 for root, _options in candidates}))
        root, eligible_by_voice = random.choice(
            [candidate for candidate in candidates if candidate[0] % 12 == pitch_class]
        )
        voice_instruments: list[InstrumentDefinition] = []
        used_names: set[str] = set()
        for eligible in eligible_by_voice:
            unused = [instrument for instrument in eligible if instrument.name not in used_names]
            instrument = random.choice(unused or eligible)
            voice_instruments.append(instrument)
            used_names.add(instrument.name)
        return voice_instruments, root

    def _actual_harmony_mode(self) -> str:
        return random.choice(self._active_harmony_modes())

    def _definition_challenge_count(self, definition: MusicDefinition) -> int:
        answer_counts = [
            self._answer_challenge_count(self._answer_name(definition, inversion))
            for inversion in self._active_inversions(len(definition.semitones))
        ]
        return min(answer_counts, default=0)

    def _active_balance_answer_names(self) -> list[str]:
        return self._active_answer_names()

    def _choose_inversion(self, definition: MusicDefinition) -> int:
        inversions = self._active_inversions(len(definition.semitones))
        return _weighted_choice_by_count(
            inversions,
            lambda inversion: self._answer_challenge_count(
                self._answer_name(definition, inversion)
            ),
        )

    def _build_harmony_answer_notes(
        self,
        root: int,
        timing: dict[str, int],
        mode: str,
        active_definitions: list[MusicDefinition] | None = None,
        voice_programs: list[int] | None = None,
    ) -> dict[str, list[MidiNote]]:
        answer_notes: dict[str, list[MidiNote]] = {}
        for definition in active_definitions or self._active_definitions():
            for inversion in self._active_inversions(len(definition.semitones)):
                answer_name = self._answer_name(definition, inversion)
                semitones = self._apply_inversion(definition.semitones, inversion)
                answer_notes[answer_name] = self._build_harmony_notes(
                    root=root,
                    semitones=semitones,
                    timing=timing,
                    mode=mode,
                    voice_programs=voice_programs,
                )
        return answer_notes

    def _harmony_answer_offsets(
        self,
        active_definitions: list[MusicDefinition],
    ) -> list[int]:
        offsets = [0]
        for definition in active_definitions:
            for inversion in self._active_inversions(len(definition.semitones)):
                offsets.extend(self._apply_inversion(definition.semitones, inversion))
        return offsets

    def _build_harmony_notes(
        self,
        root: int,
        semitones: tuple[int, ...],
        timing: dict[str, int],
        mode: str | None = None,
        voice_programs: list[int] | None = None,
    ) -> list[MidiNote]:
        mode = mode or self._actual_harmony_mode()
        programs: list[int | None] = (
            [*voice_programs[: len(semitones)]]
            if voice_programs is not None
            else [None] * len(semitones)
        )
        voices = list(zip(semitones, programs))
        if mode == "Descending":
            voices.reverse()
        if mode == "Harmonic":
            return [
                MidiNote(
                    start=0,
                    duration=timing["harmony_chord"],
                    pitch=root + semitone,
                    velocity=84,
                    program=program,
                )
                for semitone, program in voices
            ]

        return [
            MidiNote(
                start=index * timing["melodic_step"],
                duration=timing["melodic_note"],
                pitch=root + semitone,
                velocity=84,
                program=program,
            )
            for index, (semitone, program) in enumerate(voices)
        ]

    def _apply_inversion(self, semitones: tuple[int, ...], inversion: int) -> tuple[int, ...]:
        if inversion == 0:
            return semitones

        return tuple(
            sorted(
                semitone + 12 if index < inversion else semitone
                for index, semitone in enumerate(semitones)
            )
        )

    def _active_definitions(self) -> list[MusicDefinition]:
        return [
            definition
            for definition in super()._active_definitions()
            if self._active_inversions(len(definition.semitones))
        ]

    def _active_inversions(self, note_count: int) -> list[int]:
        max_inversion = max(0, note_count - 1)
        return [
            degree
            for label, degree in HARMONY_INVERSION_OPTIONS
            if degree <= max_inversion and self.inversion_vars[label].get()
        ]

    def _active_answer_names(self) -> list[str]:
        names: list[str] = []
        active_definitions = self._active_definitions()
        max_note_count = max(
            (len(definition.semitones) for definition in active_definitions),
            default=0,
        )
        for inversion in self._active_inversions(max_note_count):
            for definition in active_definitions:
                if inversion <= len(definition.semitones) - 1:
                    names.append(self._answer_name(definition, inversion))
        return names

    def _answer_name(self, definition: MusicDefinition, inversion: int) -> str:
        formula = self._inverted_formula(definition.formula, inversion)
        return f"{definition.name} ({', '.join(formula)})"

    def _inverted_formula(self, formula: tuple[str, ...], inversion: int) -> tuple[str, ...]:
        if inversion == 0:
            return formula
        return formula[inversion:] + formula[:inversion]

    def _answer_columns(self, answer_names: list[str]) -> int:
        max_name_length = max((len(name) for name in answer_names), default=0)
        if max_name_length > 18:
            return 2
        if len(answer_names) > 24:
            return 8
        return 6


class ProgressionTrainerTab(BaseTrainerTab):
    def __init__(
        self,
        parent: tk.Widget,
        player: MidiPlayer,
        settings: SettingsStore,
        instruments: tuple[InstrumentDefinition, ...],
        definitions: tuple[ProgressionDefinition, ...],
        on_start: Callable[[BaseTrainerTab], None] | None,
    ) -> None:
        super().__init__(
            parent,
            player,
            settings,
            "progressions",
            instruments,
            definitions,
            title="Harmonic function training",
            on_start=on_start,
        )

    def _build_challenge(self, definition: ProgressionDefinition) -> Challenge:
        timing = self._duration_profile()
        active_definitions = self._active_definitions()
        instrument, tonic = self._choose_instrument_and_root(
            self._progression_answer_offsets(active_definitions)
        )
        answer_notes = {
            active_definition.name: self._build_progression_notes(
                active_definition,
                tonic=tonic,
                timing=timing,
            )
            for active_definition in active_definitions
        }
        return Challenge(
            answer=definition.name,
            program=instrument.program,
            notes=answer_notes[definition.name],
            answer_notes=answer_notes,
        )

    def _build_progression_notes(
        self,
        definition: ProgressionDefinition,
        tonic: int,
        timing: dict[str, int],
    ) -> list[MidiNote]:
        notes: list[MidiNote] = []

        for index, chord in enumerate(definition.chords):
            root = tonic + chord.degree_semitones
            start = index * timing["progression_step"]
            for semitone in chord.harmony.semitones:
                notes.append(
                    MidiNote(
                        start=start,
                        duration=timing["progression_chord"],
                        pitch=root + semitone,
                        velocity=82,
                    )
                )

        return notes

    def _progression_answer_offsets(
        self,
        active_definitions: list[ProgressionDefinition],
    ) -> list[int]:
        offsets = [0]
        for definition in active_definitions:
            for chord in definition.chords:
                offsets.extend(
                    chord.degree_semitones + semitone
                    for semitone in chord.harmony.semitones
                )
        return offsets


def main() -> None:
    app = EarTrainerApp()
    app.mainloop()
