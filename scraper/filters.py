"""Filter fetched roles down to the ones worth tracking.

Three independent filters, all driven by config.json's ``filters`` block:

  * us_only          — keep only roles located in the United States
  * work_arrangement — "any" (default), "remote", "hybrid" or "onsite"
  * keywords         — keep only roles whose title matches one of the keywords

Location strings are wildly inconsistent across ATSes ("USA - Remote",
"Los Gatos,California,United States of America", "San Francisco, CA",
"Toronto, ON, CA"). We classify with an *allowlist*: a role is US if it carries
a US signal (country token, full state name, or US state code). Anything with no
US signal (Berlin, Tokyo, London) is simply not US — no country blocklist needed.

The one genuine ambiguity is the code "CA": California vs Canada. Canadian
province codes (ON, BC, AB, …) are never US state codes, so the only special
case is to reject "CA" when Canadian markers are present in the same string.
"""

from __future__ import annotations

import html
import re

US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
}

# All 50 + DC. Note: "CA" is handled separately because it collides with Canada.
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
    "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY", "DC",
}

# Major US cities that frequently appear with no state/country qualifier
# (e.g. Stripe lists "Seattle" or "San Francisco" alone). Limited to well-known,
# low-collision names — deliberately excluding ambiguous ones like Cambridge,
# Birmingham, or Manchester that are just as likely to mean the UK.
US_CITIES = {
    "san francisco", "south san francisco", "new york", "new-york", "brooklyn",
    "los angeles", "seattle", "chicago", "boston", "austin", "denver",
    "atlanta", "portland", "dallas", "houston", "san diego", "san jose",
    "philadelphia", "minneapolis", "nashville", "phoenix", "miami", "detroit",
    "palo alto", "mountain view", "sunnyvale", "bellevue",
}
# Uppercase city abbreviations (matched case-sensitively, like state codes).
US_CITY_CODES = {"SF", "NYC", "SEA"}

US_COUNTRY = re.compile(r"\b(?:united states|u\.?s\.?a\.?|u\.?s\.?|america)\b",
                        re.I)
STATE_NAME = re.compile(r"\b(?:" + "|".join(US_STATE_NAMES) + r")\b", re.I)
US_CITY = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in US_CITIES)
                     + r")\b", re.I)
# 2-letter codes appear uppercase in ATS data; match them case-sensitively so
# we don't pick up lowercase words like "or", "in", "me".
CODE = re.compile(r"\b([A-Z]{2})\b")
CANADA_MARKERS = re.compile(
    r"\b(?:canada|toronto|vancouver|montreal|ottawa|calgary|edmonton|"
    r"winnipeg|ontario|quebec|alberta|british columbia|"
    r"on|bc|ab|qc|ns|mb|sk|nl|pe)\b", re.I)


def is_us(location: str) -> bool:
    if not location:
        return False
    if US_COUNTRY.search(location):
        return True
    if STATE_NAME.search(location):
        return True
    if US_CITY.search(location):
        return True
    codes = set(CODE.findall(location))
    if codes & ((US_STATE_CODES | US_CITY_CODES) - {"CA"}):
        return True
    # "CA" counts as California only when nothing Canadian is in the string.
    if "CA" in codes and not CANADA_MARKERS.search(location):
        return True
    return False


def _compile_keywords(keywords: list[str]) -> re.Pattern | None:
    if not keywords:
        return None
    alts = "|".join(re.escape(k.strip()) for k in keywords if k.strip())
    # Word boundaries so "ui" matches "UI Engineer" but not "build"/"guide",
    # and "web" matches "Web Developer" but not "webhook".
    return re.compile(r"\b(?:" + alts + r")\b", re.I)


# ---- Work arrangement (remote / hybrid / on-site) ----------------------------
#
# Order of trust: a structured provider field (Ashby/Lever ``workplaceType``,
# Eightfold ``work_location_option``), then the location string, then specific
# phrases in the description. Descriptions are full of incidental mentions
# ("collaborate with remote teams", "hybrid cloud"), so only phrases that state
# the role's own arrangement count; anything else stays "unknown".

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_LOC_HYBRID = re.compile(r"\bhybrid\b", re.I)
_LOC_REMOTE = re.compile(r"\bremote\b", re.I)
_LOC_ONSITE = re.compile(r"\b(?:on[- ]?site|in[- ]office|office[- ]based)\b", re.I)

_NUM = r"(?:[1-5]|one|two|three|four|five)"
_DAYS = (rf"{_NUM}(?:\s*(?:-|to|or)\s*{_NUM})?\s+days?\s+"
         r"(?:(?:a|per|each|every)\s+week|/\s?week)")
_OFFICE = (r"(?:in[- ]office|on[- ]?site|in[- ]person"
           r"|(?:in|at|from) (?:the|our|an?) (?:\w+ )?office)")

_NOT_REMOTE = re.compile(
    r"\b(?:(?:is|are|be) not (?:a )?(?:fully )?remote"
    r"|not (?:eligible|open) (?:for|to) remote|no remote"
    r"|remote (?:work )?is not (?:available|an option|possible|supported))\b")
_HYBRID = [
    re.compile(rf"\b{_OFFICE}\b.{{0,40}}\b{_DAYS}"),
    re.compile(rf"\b{_DAYS}\b.{{0,40}}\b{_OFFICE}"),
    re.compile(r"\bhybrid (?:role|position|work|working|schedule|model|arrangement"
               r"|environment|policy|basis|setup)\b"),
    re.compile(r"\b(?:role|position|job) (?:is|will be) hybrid\b"),
    re.compile(r"\(hybrid\b"),
]
_REMOTE = [
    re.compile(r"\bremote[- ]eligible\b"),
    re.compile(r"\b(?:fully|100%|completely|entirely) remote\b"
               r"(?! (?:teams?|company|organization|workforce|work environments?))"),
    re.compile(r"\bremote[- ](?:first|friendly)\b"),
    re.compile(r"\b(?:role|position|job|opportunity) (?:is|can be|may be|will be|could be)"
               r" (?:fully |based )?remote(?:ly)?\b"),
    re.compile(r"\b(?:open to|welcome|considering) (?:fully )?remote"
               r" (?:candidates|applicants|locations|work)\b"),
    re.compile(r"\bremote (?:role|position|opportunity|option)\b"),
    re.compile(r"\bor remote(?:ly)?\s*[.,;)]"),
    re.compile(r"\bremote (?:in|within|from) (?:the )?(?:us|u\.s\.|united states|usa)\b"),
]
_ONSITE = [
    re.compile(r"\b(?:role|position|job) (?:is|will be) (?:an? )?(?:fully |100% )?"
               r"(?:on[- ]?site|in[- ]office|in[- ]person|office[- ]based)\b"),
    re.compile(r"\b(?:fully|100%) (?:on[- ]?site|in[- ]office|in[- ]person)\b"),
    re.compile(r"\b(?:five|5) days (?:a|per) week (?:in|at) (?:the|our) office\b"),
    re.compile(r"\b(?:on[- ]?site|in[- ]office|office[- ]based) (?:role|position)\b"),
]


def _plain(text: str) -> str:
    # Greenhouse double-escapes its HTML (&lt;p&gt;, &amp;nbsp;): unescape twice.
    t = html.unescape(html.unescape(text or ""))
    return _WS.sub(" ", _TAG.sub(" ", t)).lower()


def _from_provider(value: str) -> str | None:
    v = re.sub(r"[\s_-]", "", (value or "").lower())
    if "hybrid" in v:
        return "hybrid"
    if "remote" in v:          # "Remote", "remote_local", ...
        return "remote"
    if v in ("onsite", "office", "inoffice", "inperson"):
        return "onsite"
    return None                # "", "unspecified", unknown values


def work_arrangement(location: str, description: str = "",
                     provider_value: str = "") -> str:
    """Classify a role as "remote", "hybrid", "onsite" or "unknown"."""
    known = _from_provider(provider_value)
    if known:
        return known
    loc = location or ""
    if _LOC_HYBRID.search(loc):
        return "hybrid"
    if _LOC_REMOTE.search(loc):
        return "remote"
    if _LOC_ONSITE.search(loc):
        return "onsite"
    text = _plain(description)
    if not text:
        return "unknown"
    if _NOT_REMOTE.search(text):
        return "hybrid" if any(p.search(text) for p in _HYBRID) else "onsite"
    for kind, patterns in (("hybrid", _HYBRID), ("remote", _REMOTE),
                           ("onsite", _ONSITE)):
        if any(p.search(text) for p in patterns):
            return kind
    return "unknown"


def make_filter(filters: dict | None):
    """Return a predicate ``job -> bool`` for the configured filters.

    A None/empty config means keep everything (backwards compatible).
    """
    filters = filters or {}
    us_only = filters.get("us_only", False)
    include_remote = filters.get("include_unspecified_remote", False)
    arrangement = filters.get("work_arrangement", "any")
    if arrangement not in {"any", "remote", "hybrid", "onsite"}:
        arrangement = "any"
    kw = _compile_keywords(filters.get("keywords", []))

    def keep(job: dict) -> bool:
        if kw is not None and not kw.search(job.get("title", "")):
            return False
        loc = job.get("location", "")
        if arrangement != "any":
            kind = job.get("work_type") or work_arrangement(loc)
            if kind != arrangement:
                return False
        if us_only:
            # Office/region tags (Greenhouse) are the most reliable US signal and
            # resolve cases the free-text location can't, like "N/A".
            if any(is_us(o) for o in job.get("offices", [])):
                return True
            bare_remote = loc.strip().lower() in ("remote", "", "n/a")
            if bare_remote:
                return include_remote
            if not is_us(loc):
                return False
        return True

    return keep
