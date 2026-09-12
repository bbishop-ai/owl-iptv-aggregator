import xml.etree.ElementTree as ET
import json

from iptv_aggregator.dedupe import canonical_url, preselect_candidates, select_streams
from iptv_aggregator.epg import EPGData, match_channels
from iptv_aggregator.models import Channel, Validation
from iptv_aggregator.normalize import normalize_channel


def test_rank_primary_and_backup_and_strip_volatile_tokens():
    a = normalize_channel(Channel("Test HD", "https://a.test/live?token=one", "a"))
    b = normalize_channel(Channel("Test", "https://b.test/live", "b"))
    vals = {a.url: Validation(ok=True, height=720, latency_ms=20), b.url: Validation(ok=True, height=1080, latency_ms=40)}
    selected, stats = select_streams([a, b], vals, backups=1)
    assert [c.role for c in selected] == ["primary", "backup"]
    assert selected[0].url == b.url
    assert canonical_url("https://a.test/live?token=one") == "https://a.test/live"
    assert stats["identity_duplicates_removed"] == 0


def test_preselection_bounds_work_and_removes_token_variants():
    rows = [normalize_channel(Channel("Test", f"https://a.test/live?token={n}", str(n))) for n in range(8)]
    selected, removed = preselect_candidates(rows, per_identity=4, total_limit=10)
    assert len(selected) == 1
    assert removed == 7


def test_epg_exact_id_then_exact_name():
    one = ET.fromstring('<channel id="bbc.one.uk"><display-name>BBC One</display-name></channel>')
    epg = EPGData(channels={"bbc.one.uk": one})
    channels = [normalize_channel(Channel("BBC One HD", "https://x.test", "x"))]
    stats = match_channels(channels, epg)
    assert channels[0].tvg_id == "bbc.one.uk"
    assert stats["epg_exact_name"] == 1


def test_epg_uses_authoritative_aliases():
    station = ET.fromstring('<channel id="WABC.us"><display-name>ABC 7 New York</display-name></channel>')
    epg = EPGData(channels={"WABC.us": station})
    channel = normalize_channel(Channel("WABC-TV", "https://x.test", "x", attrs={"metadata-alt-names": json.dumps(["ABC 7 New York"])}))
    stats = match_channels([channel], epg)
    assert channel.tvg_id == "WABC.us"
    assert stats["epg_exact_name"] == 1
