"""Decoding and encoding. Everything goes through a local ffmpeg binary, so
mp3 / wav / flac / m4a all work the same way and nothing touches the network."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a"}


class AudioError(RuntimeError):
    pass


def _find_binary(name: str) -> str:
    env = os.environ.get(f"LMM_{name.upper()}")
    if env and Path(env).exists():
        return env
    exe = name + (".exe" if os.name == "nt" else "")
    # Bundled next to the app (PyInstaller) takes priority over the system one.
    bases = []
    if getattr(sys, "_MEIPASS", None):
        bases.append(Path(sys._MEIPASS))
    bases.append(Path(sys.executable).parent)
    bases.append(Path(__file__).resolve().parent.parent)
    for base in bases:
        for sub in ("bin", "."):
            cand = base / sub / exe
            if cand.exists():
                return str(cand)
    if name == "ffmpeg":
        # The pip package "imageio-ffmpeg" ships a static ffmpeg for every platform.
        try:
            import imageio_ffmpeg

            cand = imageio_ffmpeg.get_ffmpeg_exe()
            if cand and Path(cand).exists():
                return cand
        except Exception:  # noqa: BLE001 - fall through to the system one
            pass
    found = shutil.which(name)
    if found:
        return found
    raise AudioError(
        f"{name} was not found. Install it, bundle it in a 'bin' folder next to the app, "
        f"or set LMM_{name.upper()} to its path."
    )


def ffmpeg() -> str:
    return _find_binary("ffmpeg")


def ffprobe() -> str:
    return _find_binary("ffprobe")


def list_audio_files(inputs, recursive: bool = True) -> list[Path]:
    """Expand files and folders into a sorted list of supported audio files."""
    out: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            out.extend(f for f in it if f.is_file() and f.suffix.lower() in AUDIO_EXTS)
        elif p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            out.append(p)
    seen, uniq = set(), []
    for f in sorted(out, key=lambda x: str(x).lower()):
        r = f.resolve()
        if r not in seen:
            seen.add(r)
            uniq.append(f)
    return uniq


def file_id(path) -> str:
    """Content fingerprint that survives renames and moves, so a session shared
    with a friend can find the same songs in a different folder."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1()
    h.update(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(131072))
        if size > 262144:
            f.seek(size // 2)
            h.update(f.read(65536))
            f.seek(max(0, size - 131072))
            h.update(f.read(131072))
    return h.hexdigest()[:20]


def decode(path, sr: int = SR, channels: int = 2, start: float | None = None,
           duration: float | None = None, af: str | None = None) -> np.ndarray:
    """Decode to float32, shape (channels, samples). `start`/`duration` are in
    source seconds; `af` is an optional ffmpeg audio filter chain."""
    cmd = [ffmpeg(), "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.6f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.6f}"]
    cmd += ["-i", str(path), "-vn"]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(channels), "-ar", str(sr), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg could not decode {path}: {proc.stderr.decode(errors='replace')[:400]}")
    data = np.frombuffer(proc.stdout, dtype=np.float32)
    data = data[: len(data) // channels * channels]
    return np.ascontiguousarray(data.reshape(-1, channels).T)


def read_tags(path) -> dict:
    """Title / artist / album, falling back to the file name."""
    p = Path(path)
    tags = {"title": p.stem, "artist": "", "album": ""}
    try:
        import mutagen

        mf = mutagen.File(str(p), easy=True)
        if mf is not None and mf.tags:
            for key in ("title", "artist", "album"):
                val = mf.tags.get(key)
                if val:
                    tags[key] = str(val[0]).strip() or tags[key]
    except Exception:
        pass
    if not tags["artist"] and " - " in tags["title"] and tags["title"] == p.stem:
        artist, _, title = tags["title"].partition(" - ")
        tags["artist"], tags["title"] = artist.strip(), title.strip()
    return tags


def extract_cover(path, out_path) -> bool:
    """Pull embedded cover art to a jpg/png (used later by the video exporter)."""
    cmd = [ffmpeg(), "-v", "error", "-nostdin", "-y", "-i", str(path), "-an", "-frames:v", "1", str(out_path)]
    return subprocess.run(cmd, capture_output=True).returncode == 0 and Path(out_path).exists()


def write_audio(path, audio: np.ndarray, sr: int = SR, metadata: dict | None = None) -> None:
    """Write (2, n) float audio. wav = 24-bit, flac = 24-bit (max compression),
    mp3 = 320 kbps CBR."""
    path = Path(path)
    ext = path.suffix.lower()
    audio = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    if ext == ".wav":
        sf.write(str(path), audio.T, sr, subtype="PCM_24", format="WAV")
    elif ext == ".flac":
        sf.write(str(path), audio.T, sr, subtype="PCM_24", format="FLAC", compression_level=1.0)
    elif ext == ".mp3":
        cmd = [ffmpeg(), "-v", "error", "-nostdin", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2",
               "-i", "-", "-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"]
        for k, v in (metadata or {}).items():
            cmd += ["-metadata", f"{k}={v}"]
        cmd.append(str(path))
        proc = subprocess.run(cmd, input=audio.T.tobytes(), capture_output=True)
        if proc.returncode != 0:
            raise AudioError(f"mp3 encode failed: {proc.stderr.decode(errors='replace')[:400]}")
    else:
        raise AudioError(f"Unsupported output format '{ext}'. Use .wav, .mp3 or .flac.")
