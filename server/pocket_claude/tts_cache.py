"""In-Memory LRU-Cache für vorgenerierte TTS-Audio-Bytes.

Workflow:
1. Sobald Claude eine Antwort fertig gestreamt hat, triggert der Server im
   Hintergrund eine TTS-Synthese und speichert die fertigen Audio-Bytes hier
   unter dem Key `(message_id, voice, rate, provider)`.
2. Wenn der User später aufs Vorlesen-Symbol tippt, wird zuerst hier
   nachgeschaut. Cache-Hit → 0ms Server-Latenz, App spielt sofort.
3. LRU: bei Überschreitung von `MAX_BYTES` werden älteste Einträge entfernt.

Der `provider` ist im Key, weil MP3-Bytes (Edge, Grok) und Ogg-Bytes
(Gemini Web) nicht austauschbar sind — wenn der User mid-
Session den Provider wechselt, soll der Cache des anderen Providers nicht
fälschlich getroffen werden.

Der Cache lebt nur im Server-Prozess (kein Disk-Persist). Nach Restart leer.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# 200 MB — bei ~50 KB pro Antwort sind das ~4000 vorgenerierte TTS-Audios.
# Im Speicher absolut OK; bei knappen Mini-PCs ggf. reduzieren.
MAX_BYTES = 200 * 1024 * 1024


@dataclass
class CacheEntry:
    audio: bytes
    media_type: str  # "audio/mpeg" oder "audio/wav"


_cache: "OrderedDict[tuple[int, str, float, str], CacheEntry]" = OrderedDict()
_total_bytes = 0
_lock = asyncio.Lock()


def _key(message_id: int, voice: str, rate: float, provider: str
         ) -> tuple[int, str, float, str]:
    return (int(message_id), voice, round(float(rate), 3), provider)


async def get(message_id: int, voice: str, rate: float, provider: str
              ) -> Optional[CacheEntry]:
    """Cache-Lookup. Bei Hit: LRU-touch."""
    async with _lock:
        key = _key(message_id, voice, rate, provider)
        val = _cache.get(key)
        if val is not None:
            _cache.move_to_end(key)
        return val


async def put(message_id: int, voice: str, rate: float, provider: str,
              audio: bytes, media_type: str) -> None:
    """Audio in den Cache legen. Bei Überschreitung von MAX_BYTES → älteste raus."""
    global _total_bytes
    if not audio:
        return
    async with _lock:
        key = _key(message_id, voice, rate, provider)
        if key in _cache:
            _total_bytes -= len(_cache[key].audio)
        _cache[key] = CacheEntry(audio=audio, media_type=media_type)
        _cache.move_to_end(key)
        _total_bytes += len(audio)
        while _total_bytes > MAX_BYTES and _cache:
            _old_key, evicted = _cache.popitem(last=False)
            _total_bytes -= len(evicted.audio)
            log.debug("TTS-Cache eviction: %d bytes free, %d entries left",
                      len(evicted.audio), len(_cache))
    log.info(
        "TTS-Cache PUT msg=%d voice=%s rate=%.2f provider=%s (%d KB, total=%d KB / %d entries)",
        message_id, voice, rate, provider, len(audio) // 1024,
        _total_bytes // 1024, len(_cache),
    )


async def invalidate_message(message_id: int) -> int:
    """Entfernt alle Cache-Einträge für eine Message (z.B. beim Löschen).
    Returnt die Anzahl entfernter Einträge."""
    global _total_bytes
    async with _lock:
        to_remove = [k for k in _cache if k[0] == int(message_id)]
        for k in to_remove:
            _total_bytes -= len(_cache.pop(k).audio)
        return len(to_remove)


def stats() -> dict:
    """Debug-Info — wird vom Health-Endpoint o.ä. genutzt."""
    return {
        "entries": len(_cache),
        "bytes": _total_bytes,
        "max_bytes": MAX_BYTES,
    }
