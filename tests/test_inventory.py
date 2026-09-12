import json
from pathlib import Path


def test_checked_in_superset_is_complete():
    root = Path(__file__).parents[1]
    inventory = json.loads((root / "audit/upstream_inventory.json").read_text(encoding="utf-8"))
    configured = json.loads((root / "config/sources.json").read_text(encoding="utf-8"))["sources"]
    audited = {item["url"] for item in inventory["occurrences"]}
    assert audited <= {item["url"] for item in configured}
    assert len(configured) == len({item["url"] for item in configured})

