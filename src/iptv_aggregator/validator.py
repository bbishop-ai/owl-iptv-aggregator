from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import aiohttp

from .models import Channel, Validation


class Validator:
    """Incremental two-stage validator: cheap HTTP probe, then bounded ffprobe/ffmpeg."""

    def __init__(self, cache_path: Path, timeout: int, concurrency: int, ttl_hours: int, deep_limit: int):
        self.cache_path = cache_path
        self.timeout = timeout
        self.sem = asyncio.Semaphore(concurrency)
        self.ttl = timedelta(hours=ttl_hours)
        self.deep_limit = deep_limit
        self.cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    async def validate(self, channels: list[Channel]) -> dict[str, Validation]:
        results: dict[str, Validation] = {}
        pending: list[Channel] = []
        now = datetime.now(UTC)
        for channel in channels:
            cached = self.cache.get(channel.url)
            if cached and cached.get("checked_at"):
                age = now - datetime.fromisoformat(cached["checked_at"])
                if age < self.ttl:
                    cached["cached"] = True
                    results[channel.url] = Validation(**cached)
                    continue
            pending.append(channel)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "owl-iptv-aggregator/1.0"}) as session:
            probed = await asyncio.gather(*(self._http_probe(session, c) for c in pending))
        viable = [(c, v) for c, v in zip(pending, probed) if v.ok]
        deep = await asyncio.gather(*(self._media_probe(c, v) for c, v in viable[: self.deep_limit]))
        deep_map = {c.url: v for (c, _), v in zip(viable[: self.deep_limit], deep)}
        for channel, value in zip(pending, probed):
            results[channel.url] = deep_map.get(channel.url, value)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({url: value.to_dict() for url, value in results.items()}, indent=2), encoding="utf-8")
        return results

    async def _http_probe(self, session: aiohttp.ClientSession, channel: Channel) -> Validation:
        if urlsplit(channel.url).scheme not in {"http", "https"}:
            return Validation(error="unsupported in cloud probe", checked_at=datetime.now(UTC).isoformat())
        start = monotonic()
        try:
            async with self.sem, session.get(channel.url, headers={"Range": "bytes=0-65535"}, allow_redirects=True) as response:
                chunk = await response.content.read(65_536)
                ok = response.status < 400 and bool(chunk)
                return Validation(ok=ok, latency_ms=round((monotonic() - start) * 1000), checked_at=datetime.now(UTC).isoformat(), error="" if ok else f"HTTP {response.status}")
        except Exception as exc:
            return Validation(error=str(exc)[:200], checked_at=datetime.now(UTC).isoformat())

    async def _media_probe(self, channel: Channel, base: Validation) -> Validation:
        cmd = ["ffprobe", "-v", "error", "-rw_timeout", str(self.timeout * 1_000_000), "-show_entries", "stream=codec_type,width,height,avg_frame_rate", "-of", "json", channel.url]
        process = None
        try:
            async with self.sem:
                process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout + 2)
            if process.returncode:
                base.ok = False
                base.error = stderr.decode(errors="replace")[-200:]
                return base
            streams = json.loads(stdout).get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), {})
            base.width, base.height = video.get("width"), video.get("height")
            rate = video.get("avg_frame_rate", "0/1").split("/")
            base.fps = round(float(rate[0]) / max(float(rate[1]), 1), 2)
            base.frozen = await self._frozen_probe(channel.url)
            base.ok = bool(video) and base.frozen is not True
            return base
        except (FileNotFoundError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            base.error = f"media probe: {exc}"[:200]
            return base

    async def _frozen_probe(self, url: str) -> bool | None:
        cmd = ["ffmpeg", "-v", "error", "-t", "5", "-i", url, "-vf", "fps=1", "-f", "framemd5", "-"]
        process = None
        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self.timeout + 7)
            hashes = [line.rsplit(",", 1)[-1].strip() for line in stdout.decode(errors="replace").splitlines() if line and not line.startswith("#")]
            return len(hashes) >= 3 and len(set(hashes)) == 1
        except (FileNotFoundError, TimeoutError):
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            return None
