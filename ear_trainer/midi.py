from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import wave


TICKS_PER_BEAT = 480
DEFAULT_TEMPO_MICROSECONDS = 500_000
AUDIBILITY_CACHE_VERSION = 1
AUDIBILITY_SIGNAL_THRESHOLD = 16
AUDIBILITY_NOTE_DURATION_TICKS = 480
AUDIBILITY_NOTE_STEP_TICKS = 720
AUDIBILITY_ANALYSIS_DELAY_TICKS = 80

SOUNDFONT_CANDIDATES = (
    os.environ.get("EAR_TRAINER_SOUNDFONT"),
    "/usr/share/sounds/sf2/default-GM.sf2",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    "/usr/share/sounds/sf3/default-GM.sf3",
)


class PlaybackError(RuntimeError):
    pass


@dataclass(frozen=True)
class MidiNote:
    start: int
    duration: int
    pitch: int
    velocity: int = 96


class MidiPlayer:
    def __init__(self) -> None:
        self._backend = _detect_backend()
        self._lock = threading.Lock()
        self._active_playbacks: list[tuple[subprocess.Popen[bytes], Path]] = []

    def describe_backend(self) -> str:
        kind = self._backend.kind
        if kind == "fluidsynth":
            return f"fluidsynth + {self._backend.soundfont}"
        if kind == "timidity":
            return "timidity"
        if kind == "aplaymidi":
            return f"aplaymidi port {self._backend.port}"
        return "No MIDI player"

    def audibility_cache_key(self) -> str | None:
        signature = self._backend.audibility_signature()
        if signature is None:
            return None
        payload = f"{AUDIBILITY_CACHE_VERSION}:{signature}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def measure_audible_pitches(self, program: int, pitches: list[int]) -> set[int] | None:
        if self._backend.kind != "fluidsynth":
            return None
        if not self._backend.executable or not self._backend.soundfont:
            return None
        return _measure_fluidsynth_audible_pitches(
            executable=self._backend.executable,
            soundfont=self._backend.soundfont,
            program=program,
            pitches=pitches,
        )

    def play(self, program: int, notes: list[MidiNote]) -> None:
        if not notes:
            return
        if self._backend.kind is None:
            raise PlaybackError(
                "No MIDI player found. Install fluidsynth and a GM soundfont, "
                "for example: sudo apt install fluidsynth fluid-soundfont-gm"
            )

        self.stop()
        midi_bytes = build_midi(program=program, notes=notes)
        handle = tempfile.NamedTemporaryFile(prefix="ear-trainer-", suffix=".mid", delete=False)
        midi_path = Path(handle.name)
        try:
            with handle:
                handle.write(midi_bytes)
            command = self._backend.command_for(midi_path)
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            midi_path.unlink(missing_ok=True)
            raise PlaybackError(str(exc)) from exc

        with self._lock:
            self._active_playbacks.append((process, midi_path))
        threading.Thread(
            target=self._cleanup_after_playback,
            args=(process, midi_path),
            daemon=True,
        ).start()

    def stop(self) -> None:
        with self._lock:
            active_playbacks = self._active_playbacks
            self._active_playbacks = []

        for process, _midi_path in active_playbacks:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass

    def _cleanup_after_playback(self, process: subprocess.Popen[bytes], midi_path: Path) -> None:
        process.wait()
        with self._lock:
            self._active_playbacks = [
                active_playback
                for active_playback in self._active_playbacks
                if active_playback[0] is not process
            ]
        midi_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class _Backend:
    kind: str | None
    executable: str | None = None
    soundfont: str | None = None
    port: str | None = None

    def command_for(self, midi_path: Path) -> list[str]:
        if self.kind == "fluidsynth" and self.executable and self.soundfont:
            return [self.executable, "-ni", "-q", "-g", "0.9", self.soundfont, str(midi_path)]
        if self.kind == "timidity" and self.executable:
            return [self.executable, "-q", str(midi_path)]
        if self.kind == "aplaymidi" and self.executable and self.port:
            return [self.executable, "-p", self.port, str(midi_path)]
        raise PlaybackError("MIDI backend is not configured")

    def audibility_signature(self) -> str | None:
        if self.kind == "fluidsynth" and self.executable and self.soundfont:
            soundfont = Path(self.soundfont).expanduser()
            try:
                stat = soundfont.stat()
            except OSError:
                return None
            return (
                f"fluidsynth|{self.executable}|{soundfont}|"
                f"{stat.st_mtime_ns}|{stat.st_size}"
            )
        return None


def build_midi(program: int, notes: list[MidiNote]) -> bytes:
    track = bytearray()
    track += _varlen(0) + b"\xff\x51\x03" + DEFAULT_TEMPO_MICROSECONDS.to_bytes(3, "big")
    track += _varlen(0) + bytes([0xC0, max(0, min(127, program))])

    events: list[tuple[int, int, bytes]] = []
    for note in notes:
        pitch = max(0, min(127, note.pitch))
        velocity = max(1, min(127, note.velocity))
        start = max(0, note.start)
        end = max(start + 1, start + note.duration)
        events.append((start, 1, bytes([0x90, pitch, velocity])))
        events.append((end, 0, bytes([0x80, pitch, 0])))

    last_tick = 0
    for tick, _order, payload in sorted(events, key=lambda item: (item[0], item[1])):
        track += _varlen(tick - last_tick)
        track += payload
        last_tick = tick

    track += _varlen(0) + b"\xff\x2f\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_BEAT)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def _measure_fluidsynth_audible_pitches(
    executable: str,
    soundfont: str,
    program: int,
    pitches: list[int],
) -> set[int] | None:
    normalized_pitches = sorted({max(0, min(127, int(pitch))) for pitch in pitches})
    if not normalized_pitches:
        return set()

    notes = [
        MidiNote(
            start=index * AUDIBILITY_NOTE_STEP_TICKS,
            duration=AUDIBILITY_NOTE_DURATION_TICKS,
            pitch=pitch,
            velocity=120,
        )
        for index, pitch in enumerate(normalized_pitches)
    ]

    handle = tempfile.NamedTemporaryFile(prefix="ear-trainer-audibility-", suffix=".mid", delete=False)
    midi_path = Path(handle.name)
    with handle:
        handle.write(build_midi(program=program, notes=notes))

    wav_handle = tempfile.NamedTemporaryFile(
        prefix="ear-trainer-audibility-",
        suffix=".wav",
        delete=False,
    )
    wav_path = Path(wav_handle.name)
    wav_handle.close()

    try:
        result = subprocess.run(
            [
                executable,
                "-ni",
                "-q",
                "-g",
                "1.0",
                "-R",
                "0",
                "-C",
                "0",
                "-T",
                "wav",
                "-O",
                "s16",
                "-F",
                str(wav_path),
                soundfont,
                str(midi_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return None
        return _audible_pitches_from_wav(wav_path, normalized_pitches)
    except (OSError, subprocess.TimeoutExpired, wave.Error):
        return None
    finally:
        midi_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)


def _audible_pitches_from_wav(wav_path: Path, pitches: list[int]) -> set[int]:
    audible_pitches: set[int] = set()
    with wave.open(str(wav_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        return set(pitches)

    for index, pitch in enumerate(pitches):
        note_start = index * AUDIBILITY_NOTE_STEP_TICKS
        analysis_start = note_start + AUDIBILITY_ANALYSIS_DELAY_TICKS
        analysis_end = note_start + AUDIBILITY_NOTE_DURATION_TICKS
        start_frame = _ticks_to_frame(analysis_start, frame_rate)
        end_frame = _ticks_to_frame(analysis_end, frame_rate)
        if _pcm16_peak(frames, channels, start_frame, end_frame) >= AUDIBILITY_SIGNAL_THRESHOLD:
            audible_pitches.add(pitch)

    return audible_pitches


def _ticks_to_frame(ticks: int, frame_rate: int) -> int:
    seconds = (ticks / TICKS_PER_BEAT) * (DEFAULT_TEMPO_MICROSECONDS / 1_000_000)
    return max(0, int(seconds * frame_rate))


def _pcm16_peak(frames: bytes, channels: int, start_frame: int, end_frame: int) -> int:
    start = max(0, start_frame * channels * 2)
    end = max(start, end_frame * channels * 2)
    segment = frames[start:end]
    sample_count = len(segment) // 2
    if sample_count == 0:
        return 0
    peak = 0
    for index in range(sample_count):
        sample = int.from_bytes(segment[index * 2 : index * 2 + 2], "little", signed=True)
        peak = max(peak, abs(sample))
    return peak


def _detect_backend() -> _Backend:
    fluidsynth = shutil.which("fluidsynth")
    soundfont = _find_soundfont()
    if fluidsynth and soundfont:
        return _Backend(kind="fluidsynth", executable=fluidsynth, soundfont=str(soundfont))

    timidity = shutil.which("timidity")
    if timidity:
        return _Backend(kind="timidity", executable=timidity)

    midi_port = os.environ.get("EAR_TRAINER_MIDI_PORT")
    aplaymidi = shutil.which("aplaymidi")
    if aplaymidi and midi_port:
        return _Backend(kind="aplaymidi", executable=aplaymidi, port=midi_port)

    return _Backend(kind=None)


def _find_soundfont() -> Path | None:
    for candidate in SOUNDFONT_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    return None


def _varlen(value: int) -> bytes:
    value = max(0, value)
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7

    result = bytearray()
    while True:
        result.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(result)
