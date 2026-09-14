from iptv_aggregator.dedupe import select_streams
from iptv_aggregator.models import Channel, Validation


def test_soft_validation_semantics_remove_dead_keep_uncertain():
    dead = Channel("Dead", "https://dead.test/live", "aria", identity="id:dead")
    blocked = Channel("Blocked", "https://blocked.test/live", "aria", identity="id:blocked")
    selected, _ = select_streams(
        [dead, blocked],
        {
            dead.url: Validation(ok=False, error="HTTP 404"),
            blocked.url: Validation(ok=True, error="soft-kept (probe said: HTTP 403)"),
        },
        backups=0,
    )
    assert [c.name for c in selected] == ["Blocked"]


def test_aria_source_override_still_removes_confirmed_dead_entries():
    dead = Channel("Aria dead", "https://aria.test/dead", "5dab59855cb7", identity="id:aria")
    live = Channel("Aria live", "https://aria.test/live", "5dab59855cb7", identity="id:aria")
    selected, stats = select_streams(
        [dead, live],
        {dead.url: Validation(ok=False, error="HTTP 404"), live.url: Validation(ok=True)},
        backups=0,
        backups_by_source={"5dab59855cb7": 39},
    )
    assert [c.name for c in selected] == ["Aria live"]
    assert stats["identity_duplicates_removed"] == 1
