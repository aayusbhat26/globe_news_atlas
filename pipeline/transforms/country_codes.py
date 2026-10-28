"""Country code / name normalisation used by ingestion and relation arcs.

CAMEO (GDELT), ACLED and ReliefWeb all identify countries differently; this
module maps the common representations to one canonical English name.
"""
import re
import unicodedata
from typing import Iterable, List, Optional

ISO3_TO_NAME = {
    "AFG": "Afghanistan", "ALB": "Albania", "DZA": "Algeria", "AND": "Andorra",
    "AGO": "Angola", "ATG": "Antigua and Barbuda", "ARG": "Argentina", "ARM": "Armenia",
    "AUS": "Australia", "AUT": "Austria", "AZE": "Azerbaijan", "BHS": "Bahamas",
    "BHR": "Bahrain", "BGD": "Bangladesh", "BRB": "Barbados", "BLR": "Belarus",
    "BEL": "Belgium", "BLZ": "Belize", "BEN": "Benin", "BTN": "Bhutan",
    "BOL": "Bolivia", "BIH": "Bosnia and Herzegovina", "BWA": "Botswana", "BRA": "Brazil",
    "BRN": "Brunei", "BGR": "Bulgaria", "BFA": "Burkina Faso", "BDI": "Burundi",
    "CPV": "Cabo Verde", "KHM": "Cambodia", "CMR": "Cameroon", "CAN": "Canada",
    "CAF": "Central African Republic", "TCD": "Chad", "CHL": "Chile", "CHN": "China",
    "COL": "Colombia", "COM": "Comoros", "COG": "Republic of the Congo",
    "COD": "Democratic Republic of the Congo", "CRI": "Costa Rica", "CIV": "Côte d'Ivoire",
    "HRV": "Croatia", "CUB": "Cuba", "CYP": "Cyprus", "CZE": "Czechia",
    "DNK": "Denmark", "DJI": "Djibouti", "DMA": "Dominica", "DOM": "Dominican Republic",
    "ECU": "Ecuador", "EGY": "Egypt", "SLV": "El Salvador", "GNQ": "Equatorial Guinea",
    "ERI": "Eritrea", "EST": "Estonia", "SWZ": "Eswatini", "ETH": "Ethiopia",
    "FJI": "Fiji", "FIN": "Finland", "FRA": "France", "GAB": "Gabon",
    "GMB": "Gambia", "GEO": "Georgia", "DEU": "Germany", "GHA": "Ghana",
    "GRC": "Greece", "GRD": "Grenada", "GTM": "Guatemala", "GIN": "Guinea",
    "GNB": "Guinea-Bissau", "GUY": "Guyana", "HTI": "Haiti", "HND": "Honduras",
    "HUN": "Hungary", "ISL": "Iceland", "IND": "India", "IDN": "Indonesia",
    "IRN": "Iran", "IRQ": "Iraq", "IRL": "Ireland", "ISR": "Israel",
    "ITA": "Italy", "JAM": "Jamaica", "JPN": "Japan", "JOR": "Jordan",
    "KAZ": "Kazakhstan", "KEN": "Kenya", "KIR": "Kiribati", "PRK": "North Korea",
    "KOR": "South Korea", "KWT": "Kuwait", "KGZ": "Kyrgyzstan", "LAO": "Laos",
    "LVA": "Latvia", "LBN": "Lebanon", "LSO": "Lesotho", "LBR": "Liberia",
    "LBY": "Libya", "LIE": "Liechtenstein", "LTU": "Lithuania", "LUX": "Luxembourg",
    "MDG": "Madagascar", "MWI": "Malawi", "MYS": "Malaysia", "MDV": "Maldives",
    "MLI": "Mali", "MLT": "Malta", "MHL": "Marshall Islands", "MRT": "Mauritania",
    "MUS": "Mauritius", "MEX": "Mexico", "FSM": "Micronesia", "MDA": "Moldova",
    "MCO": "Monaco", "MNG": "Mongolia", "MNE": "Montenegro", "MAR": "Morocco",
    "MOZ": "Mozambique", "MMR": "Myanmar", "NAM": "Namibia", "NRU": "Nauru",
    "NPL": "Nepal", "NLD": "Netherlands", "NZL": "New Zealand", "NIC": "Nicaragua",
    "NER": "Niger", "NGA": "Nigeria", "MKD": "North Macedonia", "NOR": "Norway",
    "OMN": "Oman", "PAK": "Pakistan", "PLW": "Palau", "PSE": "Palestine",
    "PAN": "Panama", "PNG": "Papua New Guinea", "PRY": "Paraguay", "PER": "Peru",
    "PHL": "Philippines", "POL": "Poland", "PRT": "Portugal", "QAT": "Qatar",
    "ROU": "Romania", "RUS": "Russia", "RWA": "Rwanda", "KNA": "Saint Kitts and Nevis",
    "LCA": "Saint Lucia", "VCT": "Saint Vincent and the Grenadines", "WSM": "Samoa",
    "SMR": "San Marino", "STP": "Sao Tome and Principe", "SAU": "Saudi Arabia",
    "SEN": "Senegal", "SRB": "Serbia", "SYC": "Seychelles", "SLE": "Sierra Leone",
    "SGP": "Singapore", "SVK": "Slovakia", "SVN": "Slovenia", "SLB": "Solomon Islands",
    "SOM": "Somalia", "ZAF": "South Africa", "SSD": "South Sudan", "ESP": "Spain",
    "LKA": "Sri Lanka", "SDN": "Sudan", "SUR": "Suriname", "SWE": "Sweden",
    "CHE": "Switzerland", "SYR": "Syria", "TWN": "Taiwan", "TJK": "Tajikistan",
    "TZA": "Tanzania", "THA": "Thailand", "TLS": "Timor-Leste", "TGO": "Togo",
    "TON": "Tonga", "TTO": "Trinidad and Tobago", "TUN": "Tunisia", "TUR": "Turkey",
    "TKM": "Turkmenistan", "TUV": "Tuvalu", "UGA": "Uganda", "UKR": "Ukraine",
    "ARE": "United Arab Emirates", "GBR": "United Kingdom", "USA": "United States",
    "URY": "Uruguay", "UZB": "Uzbekistan", "VUT": "Vanuatu", "VAT": "Vatican City",
    "VEN": "Venezuela", "VNM": "Vietnam", "YEM": "Yemen", "ZMB": "Zambia",
    "ZWE": "Zimbabwe", "XKX": "Kosovo", "HKG": "Hong Kong",
}

ISO2_TO_NAME = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AO": "Angola",
    "AR": "Argentina", "AM": "Armenia", "AU": "Australia", "AT": "Austria",
    "AZ": "Azerbaijan", "BD": "Bangladesh", "BY": "Belarus", "BE": "Belgium",
    "BO": "Bolivia", "BA": "Bosnia and Herzegovina", "BR": "Brazil", "BG": "Bulgaria",
    "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada", "CL": "Chile",
    "CN": "China", "CO": "Colombia", "CD": "Democratic Republic of the Congo",
    "CG": "Republic of the Congo", "CR": "Costa Rica", "CI": "Côte d'Ivoire",
    "HR": "Croatia", "CU": "Cuba", "CY": "Cyprus", "CZ": "Czechia",
    "DK": "Denmark", "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt",
    "SV": "El Salvador", "EE": "Estonia", "ET": "Ethiopia", "FI": "Finland",
    "FR": "France", "GE": "Georgia", "DE": "Germany", "GH": "Ghana",
    "GR": "Greece", "GT": "Guatemala", "HN": "Honduras", "HK": "Hong Kong",
    "HU": "Hungary", "IS": "Iceland", "IN": "India", "ID": "Indonesia",
    "IR": "Iran", "IQ": "Iraq", "IE": "Ireland", "IL": "Israel",
    "IT": "Italy", "JM": "Jamaica", "JP": "Japan", "JO": "Jordan",
    "KZ": "Kazakhstan", "KE": "Kenya", "KP": "North Korea", "KR": "South Korea",
    "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos", "LV": "Latvia",
    "LB": "Lebanon", "LY": "Libya", "LT": "Lithuania", "LU": "Luxembourg",
    "MY": "Malaysia", "MV": "Maldives", "ML": "Mali", "MT": "Malta",
    "MX": "Mexico", "MD": "Moldova", "MN": "Mongolia", "ME": "Montenegro",
    "MA": "Morocco", "MZ": "Mozambique", "MM": "Myanmar", "NP": "Nepal",
    "NL": "Netherlands", "NZ": "New Zealand", "NI": "Nicaragua", "NE": "Niger",
    "NG": "Nigeria", "MK": "North Macedonia", "NO": "Norway", "OM": "Oman",
    "PK": "Pakistan", "PS": "Palestine", "PA": "Panama", "PY": "Paraguay",
    "PE": "Peru", "PH": "Philippines", "PL": "Poland", "PT": "Portugal",
    "QA": "Qatar", "RO": "Romania", "RU": "Russia", "RW": "Rwanda",
    "SA": "Saudi Arabia", "SN": "Senegal", "RS": "Serbia", "SG": "Singapore",
    "SK": "Slovakia", "SI": "Slovenia", "SO": "Somalia", "ZA": "South Africa",
    "SS": "South Sudan", "ES": "Spain", "LK": "Sri Lanka", "SD": "Sudan",
    "SE": "Sweden", "CH": "Switzerland", "SY": "Syria", "TW": "Taiwan",
    "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand", "TL": "Timor-Leste",
    "TG": "Togo", "TT": "Trinidad and Tobago", "TN": "Tunisia", "TR": "Turkey",
    "TM": "Turkmenistan", "UG": "Uganda", "UA": "Ukraine", "AE": "United Arab Emirates",
    "GB": "United Kingdom", "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VE": "Venezuela", "VN": "Vietnam", "YE": "Yemen", "ZM": "Zambia",
    "ZW": "Zimbabwe", "XK": "Kosovo",
}

# The original table omitted small states, which silently dropped their
# bilateral arcs (a Fiji endpoint could not be labelled or validated).
ISO2_TO_NAME.update({
    "AD": "Andorra", "AG": "Antigua and Barbuda", "BS": "Bahamas", "BH": "Bahrain",
    "BB": "Barbados", "BZ": "Belize", "BJ": "Benin", "BT": "Bhutan",
    "BW": "Botswana", "BN": "Brunei", "BF": "Burkina Faso", "BI": "Burundi",
    "CV": "Cabo Verde", "CF": "Central African Republic", "TD": "Chad",
    "KM": "Comoros", "DJ": "Djibouti", "DM": "Dominica", "GQ": "Equatorial Guinea",
    "ER": "Eritrea", "SZ": "Eswatini", "FJ": "Fiji", "GA": "Gabon",
    "GM": "Gambia", "GD": "Grenada", "GN": "Guinea", "GW": "Guinea-Bissau",
    "GY": "Guyana", "HT": "Haiti", "KI": "Kiribati", "LS": "Lesotho",
    "LR": "Liberia", "LI": "Liechtenstein", "MG": "Madagascar", "MW": "Malawi",
    "MH": "Marshall Islands", "MR": "Mauritania", "MU": "Mauritius",
    "FM": "Micronesia", "MC": "Monaco", "NA": "Namibia", "NR": "Nauru",
    "PW": "Palau", "PG": "Papua New Guinea", "KN": "Saint Kitts and Nevis",
    "LC": "Saint Lucia", "VC": "Saint Vincent and the Grenadines", "WS": "Samoa",
    "SM": "San Marino", "ST": "Sao Tome and Principe", "SC": "Seychelles",
    "SL": "Sierra Leone", "SB": "Solomon Islands", "SR": "Suriname",
    "TO": "Tonga", "TV": "Tuvalu", "VU": "Vanuatu", "VA": "Vatican City",
})

NAME_ALIASES = {
    "united states of america": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "usa": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "northern ireland": "United Kingdom",
    "russian federation": "Russia",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "north korea": "North Korea",
    "dprk": "North Korea",
    "burma": "Myanmar",
    "ivory coast": "Côte d'Ivoire",
    "cote d'ivoire": "Côte d'Ivoire",
    "czech republic": "Czechia",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "uae": "United Arab Emirates",
    "emirates": "United Arab Emirates",
    "vatican": "Vatican City",
    "cape verde": "Cabo Verde",
    "swaziland": "Eswatini",
    "macedonia": "North Macedonia",
    "east timor": "Timor-Leste",
    "drc": "Democratic Republic of the Congo",
    "dr congo": "Democratic Republic of the Congo",
    "democratic republic of congo": "Democratic Republic of the Congo",
    "republic of congo": "Republic of the Congo",
    "congo-brazzaville": "Republic of the Congo",
    "palestinian territories": "Palestine",
    "palestinian territory": "Palestine",
    "west bank": "Palestine",
    "gaza": "Palestine",
    "gaza strip": "Palestine",
    "hong kong": "Hong Kong",
    "kosovo": "Kosovo",
    "somaliland": "Somalia",
    "saudi": "Saudi Arabia",
}

# Spanish, French and Portuguese names appear constantly in the feeds we
# ingest. They are stored accent-free because matching normalises text with
# _ascii() first.
NAME_ALIASES.update({
    "estados unidos": "United States", "reino unido": "United Kingdom",
    "etats-unis": "United States", "etats unis": "United States",
    "royaume-uni": "United Kingdom", "royaume uni": "United Kingdom",
    "alemania": "Germany", "alemanha": "Germany", "allemagne": "Germany",
    "francia": "France", "franca": "France",
    "espana": "Spain", "espagne": "Spain", "espanha": "Spain",
    "italia": "Italy", "italie": "Italy",
    "japon": "Japan", "japao": "Japan",
    "rusia": "Russia", "russia": "Russia", "russie": "Russia",
    "ucrania": "Ukraine", "ukraina": "Ukraine",
    "brasil": "Brazil", "bresil": "Brazil", "brazil": "Brazil",
    "mexico": "Mexico", "mexique": "Mexico",
    "canada": "Canada", "argelia": "Algeria", "algerie": "Algeria",
    "argentine": "Argentina", "colombie": "Colombia",
    "chili": "Chile", "perou": "Peru", "peru": "Peru",
    "iran": "Iran", "israel": "Israel", "palestine": "Palestine",
    "inde": "India", "india": "India", "pakistan": "Pakistan",
    "nigeria": "Nigeria", "afrique du sud": "South Africa",
    "sudafrica": "South Africa", "africa do sul": "South Africa",
    "egypte": "Egypt", "egipto": "Egypt", "egito": "Egypt",
    "turquia": "Turkey", "turquie": "Turkey", "turkiye": "Turkey",
    "grece": "Greece", "grecia": "Greece", "grecia": "Greece",
    "pologne": "Poland", "polonia": "Poland",
    "suede": "Sweden", "suecia": "Sweden", "suecia": "Sweden",
    "norvege": "Norway", "noruega": "Norway",
    "finlande": "Finland", "finlandia": "Finland",
    "danemark": "Denmark", "dinamarca": "Denmark",
    "pays-bas": "Netherlands", "paises bajos": "Netherlands",
    "belgique": "Belgium", "belgica": "Belgium",
    "suisse": "Switzerland", "suiza": "Switzerland", "suica": "Switzerland",
    "autriche": "Austria", "austria": "Austria",
    "hongrie": "Hungary", "hungria": "Hungary",
    "roumanie": "Romania", "rumania": "Romania", "romenia": "Romania",
    "serbie": "Serbia", "servia": "Serbia", "croatie": "Croatia",
    "croacia": "Croatia", "indonesie": "Indonesia", "indonesia": "Indonesia",
    "philippines": "Philippines", "filipinas": "Philippines",
    "thailande": "Thailand", "tailandia": "Thailand",
    "vietnam": "Vietnam", "vietna": "Vietnam",
    "coree du sud": "South Korea", "corea del sur": "South Korea",
    "coreia do sul": "South Korea", "coree du nord": "North Korea",
    "corea del norte": "North Korea", "coreia do norte": "North Korea",
    "australie": "Australia", "australia": "Australia",
    "nouvelle-zelande": "New Zealand", "nueva zelanda": "New Zealand",
    "nova zelandia": "New Zealand", "syrie": "Syria", "siria": "Syria",
    "irak": "Iraq", "iraque": "Iraq", "afghanistan": "Afghanistan",
    "afganistan": "Afghanistan", "afeganistao": "Afghanistan",
    "yemen": "Yemen", "iemen": "Yemen", "liban": "Lebanon",
    "libano": "Lebanon", "jordanie": "Jordan", "jordania": "Jordan",
    "arabie saoudite": "Saudi Arabia", "arabia saudita": "Saudi Arabia",
    "emirats arabes unis": "United Arab Emirates",
    "emirados arabes unidos": "United Arab Emirates",
    "qatar": "Qatar", "catar": "Qatar", "maroc": "Morocco",
    "marruecos": "Morocco", "marrocos": "Morocco",
    "tunisie": "Tunisia", "tunez": "Tunisia", "tunisia": "Tunisia",
    "libye": "Libya", "libia": "Libya", "soudan": "Sudan",
    "sudan": "Sudan", "sudao": "Sudan", "ethiopie": "Ethiopia",
    "etiopia": "Ethiopia", "kenya": "Kenya", "kenia": "Kenya",
    "quenia": "Kenya", "somalie": "Somalia", "somalia": "Somalia",
    "ghana": "Ghana", "gana": "Ghana", "cote d'ivoire": "Côte d'Ivoire",
    "costa de marfil": "Côte d'Ivoire", "costa do marfim": "Côte d'Ivoire",
    "republique democratique du congo": "Democratic Republic of the Congo",
    "republica democratica del congo": "Democratic Republic of the Congo",
    "republica democratica do congo": "Democratic Republic of the Congo",
    "cuba": "Cuba", "haiti": "Haiti",
    "republica dominicana": "Dominican Republic",
    "republique dominicaine": "Dominican Republic",
    "guatemala": "Guatemala", "honduras": "Honduras",
    "salvador": "El Salvador", "nicaragua": "Nicaragua",
    "costa rica": "Costa Rica", "panama": "Panama",
    "equateur": "Ecuador", "ecuador": "Ecuador", "equador": "Ecuador",
    "bolivie": "Bolivia", "bolivia": "Bolivia",
    "paraguay": "Paraguay", "paraguai": "Paraguay",
    "uruguay": "Uruguay", "uruguai": "Uruguay",
    "venezuela": "Venezuela", "argentina": "Argentina",
    "colombia": "Colombia", "chile": "Chile",
})

# Nationality adjectives are how many headlines identify a country
# ("Bangladeshi couple", "Indian voters", "Saudi official"). Without these,
# a story can be geolocated but never tagged to the affected country.
_DEMONYMS = {
    "afghan": "Afghanistan", "afghans": "Afghanistan",
    "albanian": "Albania", "algerian": "Algeria", "american": "United States",
    "americans": "United States", "argentine": "Argentina",
    "argentinian": "Argentina", "armenian": "Armenia", "australian": "Australia",
    "austrian": "Austria", "azerbaijani": "Azerbaijan",
    "bangladeshi": "Bangladesh", "bangladeshis": "Bangladesh",
    "belarusian": "Belarus", "belgian": "Belgium", "bolivian": "Bolivia",
    "bosnian": "Bosnia and Herzegovina", "brazilian": "Brazil",
    "british": "United Kingdom", "bulgarian": "Bulgaria", "burmese": "Myanmar",
    "cambodian": "Cambodia", "cameroonian": "Cameroon", "canadian": "Canada",
    "chilean": "Chile", "chinese": "China", "colombian": "Colombia",
    "croatian": "Croatia", "cuban": "Cuba", "cypriot": "Cyprus",
    "czech": "Czechia", "danish": "Denmark", "dutch": "Netherlands",
    "ecuadorian": "Ecuador", "egyptian": "Egypt", "emirati": "United Arab Emirates",
    "emiratis": "United Arab Emirates", "estonian": "Estonia",
    "ethiopian": "Ethiopia", "filipino": "Philippines", "filipinos": "Philippines",
    "finnish": "Finland", "french": "France", "georgian": "Georgia",
    "german": "Germany", "germans": "Germany", "ghanaian": "Ghana",
    "greek": "Greece", "guatemalan": "Guatemala", "haitian": "Haiti",
    "honduran": "Honduras", "hungarian": "Hungary", "icelandic": "Iceland",
    "indian": "India", "indians": "India", "indonesian": "Indonesia",
    "iranian": "Iran", "iranians": "Iran", "iraqi": "Iraq", "iraqis": "Iraq",
    "irish": "Ireland", "israeli": "Israel", "israelis": "Israel",
    "italian": "Italy", "ivorian": "Côte d'Ivoire", "jamaican": "Jamaica",
    "japanese": "Japan", "jordanian": "Jordan", "kazakh": "Kazakhstan",
    "kenyan": "Kenya", "kuwaiti": "Kuwait", "kyrgyz": "Kyrgyzstan",
    "latvian": "Latvia", "lebanese": "Lebanon", "libyan": "Libya",
    "lithuanian": "Lithuania", "malaysian": "Malaysia", "maldivian": "Maldives",
    "malian": "Mali", "maltese": "Malta", "mexican": "Mexico",
    "moldovan": "Moldova", "mongolian": "Mongolia", "montenegrin": "Montenegro",
    "moroccan": "Morocco", "mozambican": "Mozambique", "namibian": "Namibia",
    "nepali": "Nepal", "nepalese": "Nepal", "new zealander": "New Zealand",
    "nicaraguan": "Nicaragua", "nigerian": "Nigeria", "nigerien": "Niger",
    "north korean": "North Korea", "norwegian": "Norway", "omani": "Oman",
    "pakistani": "Pakistan", "pakistanis": "Pakistan", "palestinian": "Palestine",
    "palestinians": "Palestine", "panamanian": "Panama", "paraguayan": "Paraguay",
    "peruvian": "Peru", "portuguese": "Portugal", "qatari": "Qatar",
    "romanian": "Romania", "russian": "Russia", "russians": "Russia",
    "rwandan": "Rwanda", "senegalese": "Senegal", "serbian": "Serbia",
    "singaporean": "Singapore", "slovak": "Slovakia", "slovenian": "Slovenia",
    "somali": "Somalia", "south african": "South Africa",
    "south korean": "South Korea", "spanish": "Spain", "sri lankan": "Sri Lanka",
    "sudanese": "Sudan", "south sudanese": "South Sudan", "swedish": "Sweden",
    "swiss": "Switzerland", "syrian": "Syria", "syrians": "Syria",
    "saudis": "Saudi Arabia", "turks": "Turkey",
    "taiwanese": "Taiwan", "tajik": "Tajikistan", "tanzanian": "Tanzania",
    "thai": "Thailand", "tunisian": "Tunisia", "turkish": "Turkey",
    "turkmen": "Turkmenistan", "ugandan": "Uganda", "ukrainian": "Ukraine",
    "ukrainians": "Ukraine", "uruguayan": "Uruguay", "uzbek": "Uzbekistan",
    "venezuelan": "Venezuela", "vietnamese": "Vietnam", "yemeni": "Yemen",
    "zambian": "Zambia", "zimbabwean": "Zimbabwe",
}
NAME_ALIASES.update(_DEMONYMS)


def _ascii(value: str) -> str:
    text = value.replace("’", "'").replace("‘", "'").replace("`", "'")
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


_ALIAS_LOOKUP = {_ascii(k).lower(): v for k, v in NAME_ALIASES.items()}
_CANONICAL_LOOKUP = {
    _ascii(name).lower(): name for name in set(ISO3_TO_NAME.values()) | set(ISO2_TO_NAME.values())
}

# Names shorter than this are excluded from free-text matching to avoid the
# classic "US"/"IN" false positives.
_TEXT_SAFE_MIN_LEN = 4


def canonical_country(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if len(text) == 3 and upper in ISO3_TO_NAME:
        return ISO3_TO_NAME[upper]
    if len(text) == 2 and upper in ISO2_TO_NAME:
        return ISO2_TO_NAME[upper]
    lower = _ascii(text).lower()
    if lower in _CANONICAL_LOOKUP:
        return _CANONICAL_LOOKUP[lower]
    return _ALIAS_LOOKUP.get(lower)


def canonical_countries(values: Iterable[Optional[str]]) -> List[str]:
    result: List[str] = []
    for value in values:
        name = canonical_country(value)
        if name and name not in result:
            result.append(name)
    return result


def _text_patterns() -> List[tuple]:
    pairs = {}
    for name in set(ISO3_TO_NAME.values()) | set(ISO2_TO_NAME.values()):
        pairs[_ascii(name).lower()] = name
    for alias, name in NAME_ALIASES.items():
        normalized = _ascii(alias).lower()
        if len(normalized) >= _TEXT_SAFE_MIN_LEN or normalized in {"uae", "drc", "usa"}:
            pairs[normalized] = name
    ordered = sorted(pairs.items(), key=lambda item: len(item[0]), reverse=True)
    return [(re.compile(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])"), name) for alias, name in ordered]


_TEXT_PATTERNS = _text_patterns()

# These names are also ordinary given names, surnames and US state names.
# Body text must not promote them to countries on a bare mention: "Michael B
# Jordan", "Georgia" in a company name or a person called Chad are not
# datelines. A nearby preposition, the demonym or a known city makes the
# mention explicit and keeps it.
AMBIGUOUS_COUNTRY_NAMES = {"georgia", "jordan", "chad", "guinea", "niger", "dominica"}

_AMBIGUOUS_CUES = {
    "georgia": {"tbilisi", "caucasus", "abkhazia", "ossetia"},
    "jordan": {"amman", "kingdom", "jordanian", "jordanians"},
    "chad": {"n'djamena", "ndjamena", "chadian"},
    "guinea": {"conakry", "guinean"},
    "niger": {"niamey", "nigerien"},
    "dominica": {"roseau", "dominican"},
}
_LOCATION_PREPOSITION = re.compile(
    r"(?<![a-z])(?:in|at|near|across|from|around|outside|inside|within|to|into)\s+(?:the\s+)?$"
)
_POSSESSIVE_STATE = re.compile(r"^['’]s\s+(?:king|kingdom|government|army|military|border|capital|official|officials|state|authorities)\b")


def _ascii_text(value: Optional[str]) -> str:
    return _ascii(str(value or "")).lower()


def country_mention_supported(name: str, text: str) -> bool:
    """Return True when an ambiguous country name is used as a place, not a name.

    This is deliberately conservative: an unsupported mention is dropped and
    the event stays unresolved rather than being plotted in the wrong country.
    """
    canonical = canonical_country(name)
    if not canonical:
        return False
    key = canonical.lower()
    if key not in AMBIGUOUS_COUNTRY_NAMES:
        return True
    blob = _ascii_text(text)
    if not blob:
        return False
    cues = _AMBIGUOUS_CUES.get(key, set())
    if any(cue in blob for cue in cues):
        return True
    pattern = re.compile(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])")
    for match in pattern.finditer(blob):
        before = blob[max(0, match.start() - 28): match.start()]
        after = blob[match.end(): match.end() + 48]
        if _LOCATION_PREPOSITION.search(before):
            return True
        if _POSSESSIVE_STATE.search(after):
            return True
    return False


def countries_in_text(
    *texts: Optional[str],
    limit: int = 5,
    allow_ambiguous: bool = True,
) -> List[str]:
    """Return canonical country names mentioned in free text (word-boundary match)."""
    blob = _ascii(" ".join(t for t in texts if t)).lower()
    if not blob:
        return []
    # "New Mexico" is a US state, not the country Mexico; the same applies to
    # New South Wales and Wales. Protect the longer place name from the
    # shorter country pattern.
    blob = re.sub(r"\bnew\s+mexico\b", "newmexico", blob)
    blob = re.sub(r"\bnew\s+south\s+wales\b", "newsouthwales", blob)
    found: List[str] = []
    occupied: List[tuple] = []
    for pattern, name in _TEXT_PATTERNS:
        if name in found:
            continue
        if not allow_ambiguous and not country_mention_supported(name, blob):
            continue
        for match in pattern.finditer(blob):
            start, end = match.span()
            # A shorter country name inside a longer country name (Sudan in
            # South Sudan, Guinea in Papua New Guinea) is not a second country.
            if any(start >= left and end <= right for left, right in occupied):
                continue
            found.append(name)
            occupied.append((start, end))
            if len(found) >= limit:
                return found
            break
    return found


def country_iso2(name: Optional[str]) -> Optional[str]:
    canonical = canonical_country(name)
    if not canonical:
        return None
    for code, mapped in ISO2_TO_NAME.items():
        if mapped == canonical:
            return code
    return None
