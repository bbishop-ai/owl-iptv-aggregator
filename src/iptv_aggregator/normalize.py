from __future__ import annotations

import re
import unicodedata

from .models import Channel

QUALITY_WORDS = re.compile(r"\b(?:uhd|fhd|hd|sd|4k|8k|1080p?|720p?|backup|mirror)\b", re.I)
PUNCT = re.compile(r"[^a-z0-9]+")
ENGLISH_COUNTRIES = {"au", "ca", "gb", "ie", "nz", "us"}
COUNTRY_LANGUAGES = {
    "cn": "zh", "hk": "zh", "tw": "zh", "jp": "ja", "kr": "ko",
    "ru": "ru", "ua": "uk", "fr": "fr", "de": "de", "es": "es",
    "it": "it", "pt": "pt", "br": "pt", "tr": "tr", "in": "hi",
}


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = QUALITY_WORDS.sub(" ", value)
    return PUNCT.sub(" ", value).strip()


def classify_language(channel: Channel) -> str:
    explicit = channel.language.lower().split(";")[0].split(",")[0].strip()
    aliases = {"eng": "en", "english": "en", "en-us": "en", "en-gb": "en"}
    if explicit in aliases:
        return aliases[explicit]
    if explicit and explicit != "unknown":
        return explicit[:2]
    combined = " ".join((channel.name, channel.group, channel.attrs.get("metadata-name", ""), channel.attrs.get("metadata-alt-names", ""))).lower()
    if re.search(r"(?:en\s+espa[nñ]ol|las\s+tortugas|espa[nñ]ol|castellano)", combined):
        return "es"
    if re.search(r"(?:em\s+portugu[eê]s|portugu[eê]s)", combined):
        return "pt"
    if re.search(r"(?:en\s+fran[cç]ais|fran[cç]ais)", combined):
        return "fr"
    # A regional label is not evidence of English, even when a FAST channel has a US catalog ID.
    if re.search(r"(?:latin america|latinoam[eé]rica)", combined):
        return "unknown"
    if channel.country.lower() in ENGLISH_COUNTRIES:
        return "en"
    if channel.country.lower() in COUNTRY_LANGUAGES:
        return COUNTRY_LANGUAGES[channel.country.lower()]
    group = channel.group.lower()
    if any(word in group for word in ("english", "united states", "united kingdom", "canada", "australia")):
        return "en"
    if re.search(r"[\u4e00-\u9fff]", combined):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", combined):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", combined):
        return "ko"
    if re.search(r"[\u0400-\u04ff]", combined):
        return "ru"
    if re.search(r"[\u0600-\u06ff]", combined):
        return "ar"
    # ASCII alone is weak evidence; keep it unknown so the configurable caution policy decides.
    return "unknown"


def normalize_channel(channel: Channel) -> Channel:
    channel.name = re.sub(r"\s+", " ", channel.name).strip()
    channel.language = classify_language(channel)
    key = normalized_name(channel.name)
    base_id = channel.tvg_id.split("@", 1)[0]
    channel.identity = f"id:{base_id.lower()}" if base_id else f"name:{key}"
    return channel


def language_allowed(channel: Channel, languages: list[str], allow_unknown: bool) -> bool:
    return channel.language in languages or (allow_unknown and channel.language == "unknown")
