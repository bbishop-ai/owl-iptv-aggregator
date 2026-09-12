from iptv_aggregator.normalize import language_allowed, normalize_channel, normalized_name
from iptv_aggregator.parse import parse_playlist


def test_parse_and_normalize_m3u():
    text = '#EXTM3U\n#EXTINF:-1 tvg-id="bbc.one.uk" tvg-language="English" group-title="UK",BBC One HD\nhttps://example.test/live.m3u8\n'
    channel = normalize_channel(parse_playlist(text, "sample")[0])
    assert channel.tvg_id == "bbc.one.uk"
    assert channel.language == "en"
    assert channel.identity == "id:bbc.one.uk"
    assert normalized_name(channel.name) == "bbc one"
    assert language_allowed(channel, ["en"], False)


def test_unknown_is_policy_controlled():
    channel = normalize_channel(parse_playlist("News,https://example.test/x", "sample")[0])
    assert channel.language == "unknown"
    assert not language_allowed(channel, ["en"], False)
    assert language_allowed(channel, ["en"], True)


def test_non_latin_scripts_are_not_unknown():
    channel = normalize_channel(parse_playlist("央视新闻,https://example.test/x", "sample")[0])
    assert channel.language == "zh"
    assert not language_allowed(channel, ["en"], True)


def test_feed_variants_share_identity():
    one = normalize_channel(parse_playlist('#EXTINF:-1 tvg-id="CNN.us@East",CNN\nhttps://example.test/1', "one")[0])
    two = normalize_channel(parse_playlist('#EXTINF:-1 tvg-id="CNN.us@West",CNN\nhttps://example.test/2', "two")[0])
    assert one.identity == two.identity == "id:cnn.us"
