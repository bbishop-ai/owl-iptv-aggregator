from iptv_aggregator.metadata import MetadataCatalog
from iptv_aggregator.models import Channel


def test_authoritative_metadata_enriches_language_country_and_id():
    catalog = MetadataCatalog([{"id": "CNN.us", "name": "CNN", "alt_names": [], "country": "US", "languages": ["eng"]}])
    channel = Channel("CNN", "https://example.test/live", "sample")
    assert catalog.enrich(channel) == "normalized-name"
    assert channel.tvg_id == "CNN.us"
    assert channel.country == "US"
    assert channel.language == "en"
