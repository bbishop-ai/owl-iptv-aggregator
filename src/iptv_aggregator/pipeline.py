from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .config import load_config, load_sources
from .dedupe import preselect_candidates, select_streams
from .epg import fetch_epg, match_channels, xmltv_bytes
from .normalize import language_allowed, normalize_channel
from .publish import atomic_publish, m3u_text, sanity_check
from .sources import SourceFetcher
from .validator import Validator


async def run(config_path: str) -> dict:
    cfg = load_config(config_path)
    root = Path(cfg["_root"])
    sources = load_sources(root / cfg["sources_file"])
    work = root / "build"
    stage = root / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    fetcher = SourceFetcher(work / "source-cache", cfg["fetch"]["timeout_seconds"], cfg["fetch"]["concurrency"])
    fetched = await fetcher.fetch_all(sources)
    channels = [normalize_channel(channel) for _, items, _ in fetched for channel in items]
    raw_count = len(channels)
    channels = [c for c in channels if language_allowed(c, cfg["filter"]["languages"], cfg["filter"]["allow_unknown"])]
    english_count = len(channels)
    channels, prevalidation_removed = preselect_candidates(channels, cfg["validation"]["candidates_per_identity"], cfg["validation"]["total_candidate_limit"])
    validator = Validator(work / "validation-cache.json", cfg["validation"]["timeout_seconds"], cfg["validation"]["concurrency"], cfg["validation"]["cache_ttl_hours"], cfg["validation"]["deep_probe_limit"])
    validations = await validator.validate(channels)
    selected, dedupe_stats = select_streams(channels, validations, cfg["dedupe"]["backups_per_channel"])
    epg, epg_sources = await fetch_epg(sources, cfg["epg"]["timeout_seconds"])
    epg_stats = match_channels(selected, epg, cfg["epg"]["fuzzy_threshold"])
    source_status = {source["id"]: status for source, _, status in fetched}
    validation_counts = Counter("passed" if value.ok else "failed" for value in validations.values())
    stats = {
        "generated_at": datetime.now(UTC).isoformat(),
        "upstreams_attempted": len(fetched),
        "upstreams_succeeded": sum(not status.startswith("failed") for status in source_status.values()),
        "source_status": source_status,
        "epg_source_status": epg_sources,
        "raw_channels": raw_count,
        "language_kept": english_count,
        "validation_candidates": len(channels),
        "prevalidation_candidates_removed": prevalidation_removed,
        "validation_passed": validation_counts["passed"],
        "validation_failed": validation_counts["failed"],
        **dedupe_stats,
        **epg_stats,
        "published_streams": len(selected),
        "published_primary": sum(c.role == "primary" for c in selected),
        "published_backups": sum(c.role == "backup" for c in selected),
    }
    stage.joinpath("playlist.m3u").write_text(m3u_text(selected, cfg["publish"]["epg_url"], validations), encoding="utf-8")
    stage.joinpath("epg.xml").write_bytes(xmltv_bytes(selected, epg))
    stage.joinpath("stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    stage.joinpath("index.html").write_text(_index(stats), encoding="utf-8")
    stage.joinpath(".nojekyll").write_text("", encoding="utf-8")
    sanity_check(stage, cfg["publish"]["minimum_channels"])
    atomic_publish(stage, root / cfg["publish"]["directory"])
    return stats


def _index(stats: dict) -> str:
    return "<!doctype html><meta charset=utf-8><title>Owl IPTV</title><h1>Owl IPTV</h1><ul><li><a href=playlist.m3u>Playlist</a></li><li><a href=epg.xml>EPG</a></li><li><a href=stats.json>Build stats</a></li></ul><pre>" + json.dumps(stats, indent=2) + "</pre>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/pipeline.yml")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.config)), indent=2))


if __name__ == "__main__":
    main()
