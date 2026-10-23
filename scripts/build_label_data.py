"""Build compact country/state label layers from Natural Earth.

Country labels use the provided cartographic anchor (LABEL_X/LABEL_Y); state
labels use Natural Earth's admin-1 centre point. Nothing is placed by a
bounding-box guess, so labels sit inside their own shapes.
"""
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "geo_cache"
OUT = ROOT / "frontend" / "public" / "data"

SOURCES = {
    "countries": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
    "admin1": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson",
}

COUNTRY_SHORT_NAMES = {
    "United States of America": "United States",
    "Federated States of Micronesia": "Micronesia",
    "Democratic Republic of the Congo": "DR Congo",
    "Republic of the Congo": "Congo",
    "United Republic of Tanzania": "Tanzania",
    "Bosnia and Herzegovina": "Bosnia & Herz.",
    "Central African Republic": "Central African Rep.",
    "United Arab Emirates": "UAE",
    "Trinidad and Tobago": "Trinidad & Tobago",
    "Antigua and Barbuda": "Antigua & Barbuda",
    "Saint Vincent and the Grenadines": "St. Vincent",
    "São Tomé and Príncipe": "São Tomé",
    "Czech Republic": "Czechia",
    "Equatorial Guinea": "Eq. Guinea",
    "Dominican Republic": "Dominican Rep.",
    "Papua New Guinea": "Papua New Guinea",
    "Solomon Islands": "Solomon Is.",
    "Marshall Islands": "Marshall Is.",
}


def download(name: str, url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.geojson"
    if not path.exists() or path.stat().st_size < 100:
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        path.write_bytes(response.content)
    return path


def display_name(value: str, fallback: str = "") -> str:
    text = (value or fallback or "").strip()
    if text in {"", "-99", "NA", "N/A"}:
        return ""
    return COUNTRY_SHORT_NAMES.get(text, text)


def main() -> None:
    countries = json.loads(download("countries", SOURCES["countries"]).read_text(encoding="utf-8"))
    admin1 = json.loads(download("admin1", SOURCES["admin1"]).read_text(encoding="utf-8"))

    country_labels = []
    for feature in countries.get("features", []):
        props = feature.get("properties") or {}
        lat, lng = props.get("LABEL_Y"), props.get("LABEL_X")
        if lat is None or lng is None:
            continue
        name = display_name(props.get("NAME"), props.get("NAME_EN"))
        if not name or props.get("CONTINENT") == "Antarctica":
            continue
        country_labels.append(
            {
                "name": name,
                "lat": round(float(lat), 4),
                "lng": round(float(lng), 4),
                "minLabel": round(float(props.get("MIN_LABEL") or 6), 1),
                "iso2": props.get("ISO_A2") or "",
                "level": "country",
            }
        )

    state_labels = []
    for feature in admin1.get("features", []):
        props = feature.get("properties") or {}
        lat, lng = props.get("latitude"), props.get("longitude")
        if lat is None or lng is None:
            continue
        name = display_name(props.get("name_en"), props.get("name"))
        if not name:
            continue
        state_labels.append(
            {
                "name": name,
                "admin": display_name(props.get("admin"), props.get("admin")),
                "iso2": props.get("iso_a2") or "",
                "lat": round(float(lat), 4),
                "lng": round(float(lng), 4),
                "minLabel": round(float(props.get("min_label") or 11), 1),
                "level": "state",
            }
        )

    OUT.mkdir(parents=True, exist_ok=True)
    for filename, values in (
        ("country_labels.json", country_labels),
        ("admin1_labels.json", state_labels),
    ):
        target = OUT / filename
        target.write_text(
            json.dumps(values, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"wrote {target.relative_to(ROOT)} ({len(values)} labels, {target.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
