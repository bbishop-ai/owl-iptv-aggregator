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
