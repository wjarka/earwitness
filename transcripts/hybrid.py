"""Hybrid pipeline: tekst z jednego silnika + diaryzacja z innego.

Typowy przypadek: ElevenLabs no-diarize (najczystszy tekst, per-word timestamps)
+ Parakeet (najczystsza diaryzacja, segmenty per speaker). Merge'ujemy po czasie.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .comparison import Utterance, load_ground_truth, load_macwhisper
from .formatter import format_seconds


def load_word_timestamps(raw_json_path: Path) -> list[dict]:
    """Wczytaj per-word timestamps z raw ElevenLabs response (model_dump_json)."""
    data = json.loads(raw_json_path.read_text())
    return data.get("words") or []


def _intervals(utterances: list[Utterance]) -> list[tuple[str, float, float]]:
    return [(u.speaker, u.start, u.end) for u in utterances]


def load_speaker_intervals(
    macwhisper_path: Optional[Path] = None,
    ground_truth_path: Optional[Path] = None,
) -> list[tuple[str, float, float]]:
    if macwhisper_path:
        return _intervals(load_macwhisper(macwhisper_path))
    if ground_truth_path:
        return _intervals(load_ground_truth(ground_truth_path))
    raise ValueError("Trzeba podać macwhisper_path lub ground_truth_path")


def assign_speakers(
    words: list[dict],
    intervals: list[tuple[str, float, float]],
) -> list[dict]:
    """Dla każdego słowa znajdź speakera o największym overlapie czasowym.

    Fallback: jeśli słowo wypada w lukę między segmentami, przypisz speakera
    najbliższego segmentu (najmniejszy dystans od start słowa).
    """
    sorted_iv = sorted(intervals, key=lambda x: x[1])
    out: list[dict] = []
    for w in words:
        wstart = float(w.get("start") or 0.0)
        wend = float(w.get("end") or wstart)
        if wend < wstart:
            wend = wstart

        best_sp: Optional[str] = None
        best_overlap = 0.0
        for sp, s, e in sorted_iv:
            if e <= wstart:
                continue
            if s >= wend:
                break
            overlap = min(wend, e) - max(wstart, s)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sp = sp

        if best_sp is None and sorted_iv:
            # luka: najbliższy segment po dystansie od word.start
            best_sp = min(
                sorted_iv,
                key=lambda iv: min(abs(iv[1] - wstart), abs(iv[2] - wstart)),
            )[0]

        out.append({**w, "_speaker": best_sp})
    return out


def render_segments(
    segments: list[dict],
    use_real_names: bool = False,
) -> str:
    """Wyrenderuj segmenty z thomasmol/whisper-diarization w naszym formacie.

    Input: lista dictów {speaker, start, end, text} — output thomasmol.
    Bez per-word merge'u, bo speaker jest już przypisany do całego segmentu.
    """
    label_map: dict[str, int] = {}
    lines: list[str] = []
    for seg in segments:
        sp = seg.get("speaker") or "Unknown"
        if use_real_names:
            label = sp
        else:
            if sp not in label_map:
                label_map[sp] = len(label_map) + 1
            label = f"Rozmówca {label_map[sp]}"
        start = float(seg.get("start") or 0.0)
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(f"{label} [{format_seconds(start)}] {text}")
    return "\n".join(lines) + "\n"


def render_hybrid(
    words_with_speaker: list[dict],
    use_real_names: bool = False,
) -> str:
    """Pogrupuj kolejne słowa o tym samym speakerze i wyrenderuj w naszym formacie.

    use_real_names=True zachowuje oryginalne etykiety speakerów (np. "Anna Nowak"
    z ground-truth); False mapuje na anonimowe "Rozmówca N" w kolejności pojawienia.
    """
    label_map: dict[Optional[str], int] = {}
    utterances: list[dict] = []
    cur: Optional[dict] = None

    for w in words_with_speaker:
        wtype = w.get("type", "word")
        if wtype == "audio_event":
            continue
        text = w.get("text") or ""
        sp = w.get("_speaker")

        if wtype == "spacing":
            if cur is not None:
                cur["text"] += text
            continue

        if cur is None or cur["speaker"] != sp:
            if cur is not None:
                utterances.append(cur)
            cur = {
                "speaker": sp,
                "start": float(w.get("start") or 0.0),
                "text": text,
            }
        else:
            cur["text"] += text

    if cur is not None:
        utterances.append(cur)

    lines: list[str] = []
    for u in utterances:
        sp = u["speaker"]
        if use_real_names:
            label = sp or "Unknown"
        else:
            if sp not in label_map:
                label_map[sp] = len(label_map) + 1
            label = f"Rozmówca {label_map[sp]}"
        text = u["text"].strip()
        if text:
            lines.append(f"{label} [{format_seconds(u['start'])}] {text}")
    return "\n".join(lines) + "\n"
