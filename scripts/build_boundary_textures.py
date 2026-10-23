"""Build editorial globe textures with country, state/province and disputed boundaries.

Sources (public domain):
  Natural Earth 1:50m Admin 0 Countries
  Natural Earth 1:10m Admin 1 States/Provinces
  Natural Earth 1:10m Admin 0 Disputed Areas
  Natural Earth 1:50m Admin 0 Boundary Lines, Disputed Areas
  NASA Blue Marble (day) and Black Marble (night), public domain

The rendered textures are intentionally neutral about sovereignty. Country
borders are de facto lines; disputed areas receive a translucent tint and
dashed claim lines rather than being assigned to one party.
"""
import json
import math
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance

# NASA's global mosaics are intentionally larger than Pillow's default guard.
Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "data"
CACHE = ROOT / "data" / "geo_cache"

SOURCES = {
    "countries": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
    "admin1": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson",
    "disputed_areas": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_disputed_areas.geojson",
    "disputed_lines": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_boundary_lines_disputed_areas.geojson",
}

BASES = {
    "light": "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/world.topo.bathy.200412.3x21600x10800.jpg",
    "dark": "https://eoimages.gsfc.nasa.gov/images/imagerecords/144000/144898/BlackMarble_2016_3km.jpg",
}

SIZES = {"8k": (8192, 4096), "4k": (4096, 2048)}

COLORS = {
    "light": {
        "state": (58, 46, 32, 150),
        "country": (40, 33, 24, 205),
        "disputed_fill": (141, 60, 52, 30),
        "disputed_line": (141, 60, 52, 230),
        "state_width": 3,
        "country_width": 4,
        "disputed_width": 3,
    },
    "dark": {
        "state": (214, 205, 190, 62),
        "country": (235, 227, 211, 165),
        "disputed_fill": (207, 106, 82, 30),
        "disputed_line": (221, 126, 99, 235),
        "state_width": 2,
        "country_width": 4,
        "disputed_width": 3,
    },
}


def download(name: str, url: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    suffix = Path(url).suffix or ".bin"
    target = CACHE / f"{name}{suffix}"
    if not target.exists() or target.stat().st_size < 100:
        print(f"downloading {name}…")
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        target.write_bytes(response.content)
    return target


def load_json(name: str) -> dict:
    return json.loads(download(name, SOURCES[name]).read_text(encoding="utf-8"))


def project(lng: float, lat: float, width: int, height: int):
    x = (float(lng) + 180.0) / 360.0 * width
    y = (90.0 - float(lat)) / 180.0 * height
    return x, y


def rings_for_geometry(geometry: dict):
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        for ring in coords:
            yield ring
    elif kind == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                yield ring


def lines_for_geometry(geometry: dict):
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "LineString":
        yield coords
    elif kind == "MultiLineString":
        for line in coords:
            yield line


def draw_line(draw: ImageDraw.ImageDraw, coords, fill, width, size):
    map_width, map_height = size
    points = []
    previous_x = None
    for lng, lat in coords:
        if not (math.isfinite(lng) and math.isfinite(lat)):
            continue
        x, y = project(lng, lat, map_width, map_height)
        if previous_x is not None and abs(x - previous_x) > map_width / 2:
            if len(points) > 1:
                draw.line(points, fill=fill, width=width, joint="curve")
            points = []
        points.append((x, y))
        previous_x = x
    if len(points) > 1:
        draw.line(points, fill=fill, width=width, joint="curve")


def draw_dashed_line(draw, coords, fill, width, size, dash=22, gap=16):
    map_width, map_height = size
    points = [project(lng, lat, map_width, map_height) for lng, lat in coords]
    if len(points) < 2:
        return
    on = True
    remaining = dash
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if abs(x2 - x1) > map_width / 2:
            continue
        segment = math.hypot(x2 - x1, y2 - y1)
        travelled = 0.0
        while travelled < segment:
            step = min(remaining, segment - travelled)
            start = travelled / segment
            end = (travelled + step) / segment
            if on:
                draw.line(
                    [
                        (x1 + (x2 - x1) * start, y1 + (y2 - y1) * start),
                        (x1 + (x2 - x1) * end, y1 + (y2 - y1) * end),
                    ],
                    fill=fill,
                    width=width,
                )
            travelled += step
            remaining -= step
            if remaining <= 0:
                on = not on
                remaining = dash if on else gap


def draw_fill(draw, coords, fill, size):
    map_width, map_height = size
    points = [project(lng, lat, map_width, map_height) for lng, lat in coords]
    if len(points) < 3:
        return
    if any(abs(points[i + 1][0] - points[i][0]) > map_width / 2 for i in range(len(points) - 1)):
        return
    draw.polygon(points, fill=fill)


def grade_base(image: Image.Image, theme: str) -> Image.Image:
    image = image.convert("RGB")
    if theme == "light":
        image = ImageEnhance.Color(image).enhance(0.46)
        image = ImageEnhance.Contrast(image).enhance(0.98)
        image = ImageEnhance.Brightness(image).enhance(1.02)
        wash = Image.new("RGB", image.size, (232, 221, 202))
        return Image.blend(image, wash, 0.12)
    image = ImageEnhance.Color(image).enhance(0.8)
    image = ImageEnhance.Contrast(image).enhance(1.02)
    image = ImageEnhance.Brightness(image).enhance(1.06)
    wash = Image.new("RGB", image.size, (20, 22, 24))
    return Image.blend(image, wash, 0.08)


def build(theme: str):
    base_path = download(f"earth_{theme}_hires", BASES[theme])
    base = Image.open(base_path)
    width, height = SIZES["8k"]
    # Let JPEG decoders work at a reduced DCT scale instead of materialising
    # the full 21600 x 10800 frame in memory.
    try:
        base.draft("RGB", (width, height))
    except Exception:
        pass
    base = base.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    base = grade_base(base, theme)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    palette = COLORS[theme]

    countries = load_json("countries")
    admin1 = load_json("admin1")
    disputed = load_json("disputed_areas")
    disputed_lines = load_json("disputed_lines")

    print(f"[{theme}] tinting disputed areas…")
    for feature in disputed.get("features", []):
        geometry = feature.get("geometry") or {}
        for ring in rings_for_geometry(geometry):
            draw_fill(draw, ring, palette["disputed_fill"], (width, height))

    print(f"[{theme}] drawing state/province lines…")
    for feature in admin1.get("features", []):
        geometry = feature.get("geometry") or {}
        for ring in rings_for_geometry(geometry):
            draw_line(draw, ring, palette["state"], palette["state_width"], (width, height))

    print(f"[{theme}] drawing country borders…")
    for feature in countries.get("features", []):
        geometry = feature.get("geometry") or {}
        for ring in rings_for_geometry(geometry):
            draw_line(draw, ring, palette["country"], palette["country_width"], (width, height))

    print(f"[{theme}] drawing disputed claim boundaries…")
    for feature in disputed_lines.get("features", []):
        geometry = feature.get("geometry") or {}
        for line in lines_for_geometry(geometry):
            draw_dashed_line(
                draw,
                line,
                palette["disputed_line"],
                palette["disputed_width"],
                (width, height),
            )

    composed = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    OUT.mkdir(parents=True, exist_ok=True)
    for label, target_size in SIZES.items():
        rendered = composed if label == "8k" else composed.resize(target_size, Image.Resampling.LANCZOS)
        target = OUT / f"earth-{theme}-boundaries-{label}.webp"
        rendered.save(target, "WEBP", quality=88, method=6)
        print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    for theme_name in ("light", "dark"):
        build(theme_name)
