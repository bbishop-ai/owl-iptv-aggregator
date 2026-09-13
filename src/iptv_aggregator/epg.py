from __future__ import annotations

import asyncio
import gzip
import io
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from rapidfuzz.fuzz import ratio, token_sort_ratio

from .models import Channel
from .normalize import normalized_name


JUNK_WORDS = re.compile(r"\b(?:360p|480p|576p|216p|uhd|fhd|hd|sd|4k|8k|backup|mirror|not 24 7)\b")


def quality_stripped(name: str) -> str:
    """normalized_name with resolution/quality/availability junk removed (join-only)."""
    return re.sub(r"\s+", " ", JUNK_WORDS.sub(" ", normalized_name(name))).strip()


@dataclass
class EPGData:
    channels: dict[str, ET.Element] = field(default_factory=dict)
    programmes: dict[str, list[ET.Element]] = field(default_factory=lambda: defaultdict(list))


def normalized_epg_id(value: str) -> str:
    """Collapse known XMLTV provider suffixes without guessing across channels."""
    value = value.strip().casefold().split("@", 1)[0]
    is_local = bool(re.search(r"\.us_locals\d+$", value))
    value = re.sub(r"\.us_locals\d+$", ".us", value)
    value = re.sub(r"(\.[a-z]{2})\d+$", r"\1", value)
    if is_local:
        value = re.sub(r"-(?:d|dt|ld|cd|tv)(?=\.us$)", "", value)
    return value


async def fetch_epg(sources: list[dict[str, Any]], timeout_seconds: int = 45, programme_ids: set[str] | None = None, programme_names: set[str] | None = None) -> tuple[EPGData, dict[str, str]]:
    enabled = [s for s in sources if s.get("enabled", True) and s.get("kind") == "epg"]
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    statuses: dict[str, str] = {}
    data = EPGData()
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "owl-iptv-aggregator/1.0"}) as session:
        async def one(source):
            try:
                async with session.get(source["url"], allow_redirects=True) as response:
                    response.raise_for_status()
                    raw = await response.read()
                stream = gzip.GzipFile(fileobj=io.BytesIO(raw)) if raw[:2] == b"\x1f\x8b" else io.BytesIO(raw)
                parsed = EPGData()
                wanted_ids = set(programme_ids or set())
                wanted_id_keys = {normalized_epg_id(value) for value in wanted_ids}
                root = None
                for event, element in ET.iterparse(stream, events=("start", "end")):
                    if event == "start" and root is None:
                        root = element
                    if event != "end":
                        continue
                    if element.tag == "channel" and element.get("id"):
                        epg_id = element.get("id", "")
                        parsed.channels[epg_id] = element
                        if normalized_epg_id(epg_id) in wanted_id_keys:
                            wanted_ids.add(epg_id)
                        if any(normalized_name(display.text or "") in (programme_names or set()) for display in element.findall("display-name")):
                            wanted_ids.add(epg_id)
                    elif element.tag == "programme" and element.get("channel") in wanted_ids:
                        parsed.programmes[element.get("channel", "")].append(element)
                    elif element.tag == "programme":
                        element.clear()
                    if root is not None and element.tag in {"channel", "programme"}:
                        root.clear()
                return source, parsed, "succeeded"
            except Exception as exc:
                return source, None, f"failed: {exc}"
        results = await asyncio.gather(*(one(source) for source in enabled))
    for source, parsed, status in results:
        statuses[source["id"]] = status
        if parsed is None:
            continue
        for channel_id, element in parsed.channels.items():
            if channel_id and channel_id not in data.channels:
                data.channels[channel_id] = element
        for channel_id, programmes in parsed.programmes.items():
            data.programmes[channel_id].extend(programmes)
    return data, statuses


def match_channels(channels: list[Channel], epg: EPGData, fuzzy_threshold: int = 96):
    # Index both the raw normalized names and quality-stripped variants. The
    # stripped variants let "Anime x HIDIVE (720p)" join "ANIME x HIDIVE" while
    # the raw variants keep resolution variants (e.g. two feeds of one channel)
    # distinguishable for channels that carry them.
    names: dict[str, list[str]] = defaultdict(list)
    ids: dict[str, list[str]] = defaultdict(list)
    for epg_id, element in epg.channels.items():
        ids[normalized_epg_id(epg_id)].append(epg_id)
        for display in element.findall("display-name"):
            raw = normalized_name(display.text or "")
            if raw:
                names[raw].append(epg_id)
            stripped = quality_stripped(display.text or "")
            if stripped and stripped != raw:
                names[stripped].append(epg_id)
    stats = {"epg_exact_id": 0, "epg_normalized_id": 0, "epg_exact_name": 0, "epg_fuzzy": 0, "epg_unmatched": 0}
    for channel in channels:
        if channel.tvg_id in epg.channels:
            stats["epg_exact_id"] += 1
            continue
        normalized_ids = ids.get(normalized_epg_id(channel.tvg_id), []) if channel.tvg_id else []
        if len(normalized_ids) == 1:
            channel.tvg_id = normalized_ids[0]
            stats["epg_normalized_id"] += 1
            continue
        try:
            alt_names = json.loads(channel.attrs.get("metadata-alt-names", "[]"))
        except json.JSONDecodeError:
            alt_names = []
        keys = set()
        for value in [channel.tvg_name, channel.name, channel.attrs.get("metadata-name", ""), *alt_names]:
            if value:
                keys.add(normalized_name(value))
                keys.add(quality_stripped(value))
        keys.discard("")
        exact_ids = {ids[0] for key in keys for ids in [names.get(key, [])] if len(ids) == 1}
        if len(exact_ids) == 1:
            channel.tvg_id = exact_ids.pop()
            stats["epg_exact_name"] += 1
            continue
        # Fuzzy: compare word-order-insensitively and require a unique best target.
        scored = sorted(((max((token_sort_ratio(key, candidate) for key in keys), default=0), ids) for candidate, ids in names.items()), reverse=True)
        if scored and scored[0][0] >= fuzzy_threshold and len(scored[0][1]) == 1 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            channel.tvg_id = scored[0][1][0]
            stats["epg_fuzzy"] += 1
        else:
            stats["epg_unmatched"] += 1
    return stats


def xmltv_bytes(channels: list[Channel], epg: EPGData) -> bytes:
    root = ET.Element("tv", {"generator-info-name": "owl-iptv-aggregator"})
    ids = {channel.tvg_id for channel in channels if channel.tvg_id}
    for epg_id in sorted(ids):
        if epg_id in epg.channels:
            root.append(epg.channels[epg_id])
        for programme in epg.programmes.get(epg_id, []):
            root.append(programme)
    buffer = io.BytesIO()
    ET.ElementTree(root).write(buffer, encoding="utf-8", xml_declaration=True)
    return buffer.getvalue()
