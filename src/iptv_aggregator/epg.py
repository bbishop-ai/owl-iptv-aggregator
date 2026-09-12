from __future__ import annotations

import asyncio
import gzip
import io
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from rapidfuzz.fuzz import ratio

from .models import Channel
from .normalize import normalized_name


@dataclass
class EPGData:
    channels: dict[str, ET.Element] = field(default_factory=dict)
    programmes: dict[str, list[ET.Element]] = field(default_factory=lambda: defaultdict(list))


async def fetch_epg(sources: list[dict[str, Any]], timeout_seconds: int = 45) -> tuple[EPGData, dict[str, str]]:
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
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                return source, ET.fromstring(raw), "succeeded"
            except Exception as exc:
                return source, None, f"failed: {exc}"
        results = await asyncio.gather(*(one(source) for source in enabled))
    for source, root, status in results:
        statuses[source["id"]] = status
        if root is None:
            continue
        for element in root.findall("channel"):
            channel_id = element.get("id", "")
            if channel_id and channel_id not in data.channels:
                data.channels[channel_id] = element
        for element in root.findall("programme"):
            if element.get("channel"):
                data.programmes[element.get("channel", "")].append(element)
    return data, statuses


def match_channels(channels: list[Channel], epg: EPGData, fuzzy_threshold: int = 96):
    names: dict[str, list[str]] = defaultdict(list)
    for epg_id, element in epg.channels.items():
        for display in element.findall("display-name"):
            key = normalized_name(display.text or "")
            if key:
                names[key].append(epg_id)
    stats = {"epg_exact_id": 0, "epg_exact_name": 0, "epg_fuzzy": 0, "epg_unmatched": 0}
    for channel in channels:
        if channel.tvg_id in epg.channels:
            stats["epg_exact_id"] += 1
            continue
        key = normalized_name(channel.tvg_name or channel.name)
        if len(names.get(key, [])) == 1:
            channel.tvg_id = names[key][0]
            stats["epg_exact_name"] += 1
            continue
        scored = sorted(((ratio(key, candidate), ids) for candidate, ids in names.items()), reverse=True)
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
