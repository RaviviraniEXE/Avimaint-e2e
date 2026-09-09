from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
_NUMBER_ALT = "|".join(NUMBER_WORDS)


def canonical_problem_key(text: str) -> str:
    """The exact symmetric key fixed by the final Selective protocol."""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    value = re.sub(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", r" ratio_\1_\2 ", value)
    value = re.sub(r"#\s*(\d+)\b", r" num_\1 ", value)
    value = re.sub(r"\b(?:no\.?|number)\s*(\d+)\b", r" num_\1 ", value)

    def word_number(match: re.Match[str]) -> str:
        return f" num_{NUMBER_WORDS[match.group(1)]} "

    value = re.sub(rf"\bnumber\s+({_NUMBER_ALT})\b", word_number, value)
    value = re.sub(r"\b(?:l\s*/\s*h|left[ -]?hand)\b", " left ", value)
    value = re.sub(r"\b(?:r\s*/\s*h|right[ -]?hand)\b", " right ", value)
    value = re.sub(r"\bfwd\b", " forward ", value)
    value = re.sub(r"\baft\b", " rear ", value)
    aliases = {
        "cyls": "cylinder", "cylinders": "cylinder", "cyl": "cylinder",
        "intakes": "intake", "gaskets": "gasket", "magnetos": "magneto",
        "mags": "magneto", "baffles": "baffle",
    }
    for source, target in aliases.items():
        value = re.sub(rf"\b{re.escape(source)}\b", target, value)
    value = re.sub(r"[^a-z0-9_]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def display_problem_key(text: str) -> str:
    """Presentation-only grouping; never used for the thesis vote or split."""
    value = canonical_problem_key(text)
    aliases = {"eng": "engine", "engs": "engine"}
    tokens = [aliases.get(token, token) for token in value.split()]
    tokens = [token for token in tokens if token not in {"a", "an", "the", "is", "are", "was", "were"}]
    return " ".join(tokens)


def stable_display_group(text: str) -> str:
    return "DPG-" + hashlib.sha256(display_problem_key(text).encode("utf-8")).hexdigest()[:16]


ACTION_FAMILIES = ("Replace", "Repair", "Inspect", "Adjust", "Service", "Diagnose", "Calibrate")

_ISSUES = (
    ("leak", (r"leak", r"seep", r"weep")),
    ("crack", (r"crack", r"fractur", r"split")),
    ("wear", (r"\bworn", r"\bwear\b", r"erod", r"pitt", r"scor", r"gall")),
    ("loose", (r"loose", r"\bplay\b", r"backlash", r"wobbl")),
    ("corrosion", (r"corro", r"rust", r"oxidi")),
    ("burnt", (r"burn", r"scorch", r"charred", r"overheat")),
    ("broken", (r"broke", r"broken", r"snapp", r"separat", r"\bbent", r"deform", r"collaps")),
    ("low compression", (r"low compress", r"no compress", r"lost compress", r"weak cylinder")),
    ("rough running", (r"rough", r"misfir", r"backfir", r"surg", r"sputter", r"stumbl")),
    ("vibration", (r"vibrat", r"shak", r"shudder")),
    ("power loss", (r"power loss", r"los(?:e|es|ing|t) power", r"low power", r"partial power")),
    ("will not start", (r"won.?t start", r"will not start", r"no start", r"hard start")),
    ("quit / shutdown", (r"\bquit", r"shut ?down", r"died", r"cut ?out", r"stall")),
    ("noise", (r"noise", r"nois", r"knock", r"grind", r"squeal", r"clunk", r"tick")),
    ("smoke", (r"smok",)),
    ("contamination", (r"contaminat", r"debris", r"metal", r"blocked", r"clog", r"restrict")),
    ("chafing", (r"chaf", r"fray")),
    ("stuck / binding", (r"stuck", r"seiz", r"bind", r"jam", r"frozen")),
    ("inoperative", (r"inop", r"inoperativ", r"not work", r"intermittent", r"erratic", r"fluctuat")),
    ("missing / damaged", (r"missing", r"damag", r"\bhole", r"punctur", r"\btorn", r"\bnick", r"gouge", r"dent")),
    ("high reading", (r"\bhigh\b", r"excessive", r"over ?temp", r"over ?press")),
    ("low reading", (r"\blow\b", r"insufficient", r"\bweak\b")),
)


@lru_cache(maxsize=32768)
def issue_family(text: str) -> str | None:
    value = str(text or "").lower()
    for label, patterns in _ISSUES:
        if any(re.search(pattern, value) for pattern in patterns):
            return label
    return None


_COMPONENT_TERMS = {
    "intake gasket", "intake gaskets", "exhaust gasket", "rocker cover", "rocker cover gasket",
    "rocker cover gaskets", "rocker covers", "rocker gasket", "rocker gaskets",
    "rocker cover screw", "rocker cover screws", "baffle seal", "baffle seals",
    "baffle plug", "baffle plugs", "baffle screw", "baffle screws", "valve cover gasket",
    "fuel servo", "fuel pump", "fuel injector", "fuel line", "fuel filter", "fuel tank",
    "oil filter", "oil cooler", "oil line", "oil seal", "oil pump", "oil screen",
    "spark plug", "exhaust valve", "intake valve", "exhaust pipe", "exhaust stack",
    "exhaust system", "exhaust manifold", "cylinder head", "engine mount", "motor mount",
    "vacuum pump", "vacuum system", "air filter", "induction hose", "induction system",
    "landing gear", "nose gear", "main gear", "nose wheel", "brake disc", "brake pad",
    "brake line", "brake caliper", "master cylinder", "wheel bearing", "tail wheel",
    "propeller governor", "prop governor", "prop hub", "spinner bulkhead", "magneto drive",
    "ignition harness", "ignition switch", "ignition lead", "starter adapter",
    "voltage regulator", "alternator belt", "cabin heat", "carburetor heat",
    "mixture control", "throttle cable", "control cable", "push rod", "push rod tube",
    "valve guide", "valve spring", "valve seat", "piston ring", "connecting rod",
    "crankcase half", "cylinder barrel", "baffle seal", "engine baffle",
    "engine", "eng", "cylinder", "cyl", "piston", "valve", "gasket", "gaskets", "magneto", "mag",
    "carburetor", "carb", "exhaust", "muffler", "intake", "intakes", "manifold",
    "baffle", "baffles", "hose", "seal", "bearing", "crankshaft", "camshaft",
    "alternator", "generator", "starter", "battery", "propeller", "prop", "governor",
    "tire", "tyre", "brake", "strut", "gear", "injector", "nozzle", "filter", "line",
    "fitting", "clamp", "bracket", "mount", "tube", "cable", "switch", "sensor", "gauge",
    "light", "antenna", "door", "window", "windshield", "seat", "belt", "actuator", "pump",
    "tank", "cap", "screw", "bolt", "nut", "fastener", "rivet", "panel", "cowl", "cowling",
    "fairing", "flap", "aileron", "rudder", "elevator", "trim", "spinner", "hub", "boot",
    "duct", "vent", "regulator", "solenoid", "relay", "breaker", "wire", "harness",
    "connector", "terminal", "plug", "coil", "distributor", "pushrod", "rocker",
}
_COMPONENT_CANON = {
    "eng": "engine", "engines": "engine", "cyl": "cylinder", "cyls": "cylinder",
    "cylinders": "cylinder", "mag": "magneto", "mags": "magneto",
    "magnetos": "magneto", "carb": "carburetor", "prop": "propeller",
    "tyre": "tire", "baffles": "baffle", "intakes": "intake", "pushrod": "push rod",
    "motor mount": "engine mount", "valve cover gasket": "rocker cover gasket",
    "intake gaskets": "intake gasket", "rocker covers": "rocker cover",
    "rocker cover gaskets": "rocker cover gasket", "rocker cover screws": "rocker cover screw",
    "rocker covers screws": "rocker cover screw", "baffle seals": "baffle seal",
    "rocker gasket": "rocker cover gasket", "rocker gaskets": "rocker cover gasket",
    "baffle plugs": "baffle plug", "baffle screws": "baffle screw",
    "gaskets": "gasket", "screws": "screw", "plugs": "plug", "rivets": "rivet",
}
_COMPONENT_RE = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in sorted(_COMPONENT_TERMS, key=lambda item: (-len(item.split()), -len(item)))) + r")\b",
    re.IGNORECASE,
)


def canonical_component(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
    cleaned = re.sub(r"\b(?:left|right)[ -]?hand\s+", "", cleaned)
    return _COMPONENT_CANON.get(cleaned, cleaned)


def find_components(text: str) -> list[str]:
    result: dict[str, None] = {}
    for match in _COMPONENT_RE.finditer(str(text or "")):
        result.setdefault(canonical_component(match.group(0)), None)
    return list(result)


def merge_components(text: str, learned: list[str]) -> list[str]:
    lexical = find_components(text)
    values = [canonical_component(value) for value in learned if canonical_component(value)]
    values.extend(value for value in lexical if value not in values)
    # If the text explicitly contains a more specific phrase, suppress only its
    # generic substring. Distinct parts such as "intake" and "intake gasket"
    # remain separate across records.
    specific = [value for value in values if " " in value]
    filtered = [
        value for value in values
        if not any(value != phrase and re.search(rf"\b{re.escape(value)}\b", phrase) for phrase in specific)
    ]
    return list(dict.fromkeys(filtered))


def target_component(values: list[str]) -> str:
    """Choose the most specific maintenance item, not a container substring."""
    canonical = list(dict.fromkeys(canonical_component(value) for value in values if canonical_component(value)))
    if not canonical:
        return ""
    return max(enumerate(canonical), key=lambda item: (len(item[1].split()), item[0]))[1]


# Reviewed presentation aliases. These are deliberately narrow and are never
# used by the frozen RQ4 retrieval protocol. They only prevent a physical
# defect from being split across labels in descriptive dashboard views.
DEFECT_PRESENTATION_ALIASES = {
    "intake": "intake gasket",
    "rocker cover": "rocker cover gasket",
}


def defect_component(value: str) -> str:
    canonical = canonical_component(value)
    return DEFECT_PRESENTATION_ALIASES.get(canonical, canonical)


def display_location(value: str) -> str:
    canonical = canonical_location(value)
    if canonical.startswith("num_"):
        return f"number {canonical.removeprefix('num_')}"
    if canonical in {"left", "right"}:
        return f"{canonical}-hand"
    return canonical.replace("_", " ")


_LOCATION_RE = re.compile(
    r"(?<!\w)(#\s?\d+|number\s+(?:\d+|" + _NUMBER_ALT + r")|l\.?/?h\.?|r\.?/?h\.?|left(?:-hand)?|right(?:-hand)?|front|rear|forward|aft|upper|lower|inboard|outboard)\b",
    re.IGNORECASE,
)


def find_locations(text: str) -> list[str]:
    values: list[str] = []
    for match in _LOCATION_RE.finditer(str(text or "")):
        value = match.group(0).strip().lower()
        if re.fullmatch(r"l\.?/?h\.?", value):
            value = "left"
        elif re.fullmatch(r"r\.?/?h\.?", value):
            value = "right"
        elif value == "left-hand":
            value = "left"
        elif value == "right-hand":
            value = "right"
        if value not in values:
            values.append(value)
    return values


def canonical_location(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if re.fullmatch(r"#\s*\d+", cleaned):
        return "num_" + re.search(r"\d+", cleaned).group(0)
    digit = re.fullmatch(r"(?:no\.?|number)\s*(\d+)", cleaned)
    if digit:
        return "num_" + digit.group(1)
    word = re.fullmatch(r"number\s+(" + _NUMBER_ALT + r")", cleaned)
    if word:
        return f"num_{NUMBER_WORDS[word.group(1)]}"
    if re.fullmatch(r"l\.?/?h\.?|left(?:-hand)?", cleaned):
        return "left"
    if re.fullmatch(r"r\.?/?h\.?|right(?:-hand)?", cleaned):
        return "right"
    if cleaned == "aft":
        return "rear"
    if cleaned == "fwd":
        return "forward"
    return cleaned


def normalized_locations(text: str, learned: list[str] | None = None) -> list[str]:
    values: list[str] = []
    # SpERT can return a compound LOC span such as "NUMBER ONE AND NUMBER
    # THREE". Split it through the same protected-token parser rather than
    # preserving a third, duplicate location label.
    for learned_value in learned or []:
        parsed = find_locations(learned_value)
        if parsed:
            values.extend(canonical_location(value) for value in parsed)
            continue
        canonical = canonical_location(learned_value)
        if canonical.startswith("num_") or canonical in {
            "left", "right", "front", "rear", "forward", "upper", "lower", "inboard", "outboard"
        }:
            values.append(canonical)
    values.extend(canonical_location(value) for value in find_locations(text))
    return list(dict.fromkeys(value for value in values if value))


def normalize_query_for_display(text: str) -> str:
    """Conservative rules-first display adapter; numbers remain digits."""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    replacements = (
        (r"\bL\s*/\s*H\b", "left-hand"), (r"\bR\s*/\s*H\b", "right-hand"),
        (r"\bENG\b", "engine"), (r"\bCYLS?\b", "cylinder"),
        (r"\bMAGS?\b", "magneto"), (r"\bEXC\b", "excessive"),
        (r"#\s*(\d+)\b", r"number \1"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip().lower()
    if value:
        value = value[0].upper() + value[1:]
    for acronym in ("rpm", "psi", "egt", "cht"):
        value = re.sub(rf"\b{acronym}\b", acronym.upper(), value, flags=re.IGNORECASE)
    if value and value[-1] not in ".?!":
        value += "."
    return value


def looks_truncated(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    return bool(re.search(r"(?:\bAND|\bOR|\bTHE|\bTO|\bFROM|\bNO|\bWITH|\b&)$", value.rstrip(".,;:").upper()))
