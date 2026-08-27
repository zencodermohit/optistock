"""Re-stock the demo catalogue with real products and their own photographs.

The seeded catalogue is credible but invented. This swaps in real listings from
a public Flipkart export so that every product on screen is a thing that
actually exists, with the photograph that actually belongs to it.

The single rule that makes this work is that a product's NAME and its PICTURE
come from the SAME source row. An earlier attempt kept the existing names and
went looking for photographs to match them, which produced an inflatable hippo
on a "Featherlite Visitor Chair" and a wine rack on a "Netgear Rack Mount" --
the words overlap between consumer retail and warehouse supply, the products do
not. Taking both fields from one row makes a mismatch impossible by
construction rather than by careful matching.

WHAT IS NOT TOUCHED, and this is the point of the whole exercise: revenue, unit
cost, selling price, stock levels, sales history, ABC class, forecasts, alerts
and purchase orders. Every number the screens actually demonstrate is left
exactly as it was. Only `name` and `image_url` change.

SKUs are also left alone. They are opaque codes, but their leading segment is
not -- ELEC, FURN, NETW -- so each OptiStock category draws from source
categories that keep that segment honest. A phone accessory landing in ELEC is
fine; a saree landing there is not. The middle segment (LAP, MON) does go stale,
which is the price of not rewriting an identifier that scan-idempotency records
still refer to.

    python -m scripts.recatalogue --plan    # choose, download, write the outputs
    python -m scripts.recatalogue --apply   # write names and image paths in

Images are downloaded, shrunk and served from our own origin. The source CDN
answers on http and returns 403 on https -- measured, not assumed -- and this
application is https, so hotlinking would render a perfect catalogue on a
developer's localhost and a page of broken frames in production.
"""

import argparse
import csv
import io
import json
import logging
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("recatalogue")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "flipkart_com-ecommerce_sample.csv"
IMAGE_DIR = ROOT / "frontend" / "public" / "catalogue"
PLAN = ROOT / "docs" / "catalogue_plan.json"
CSV_OUT = ROOT / "docs" / "catalogue_products.csv"

#: Twice the 80px a thumbnail draws at, so it stays sharp on a retina screen
#: and not a pixel larger. The whole set lands well under a megabyte, which is
#: what lets a 200-row grid paint instantly over conference Wi-Fi.
THUMB_PX = 160

#: Where each OptiStock category draws from. Two forms, because the source is
#: organised for a shopper and this catalogue is organised for a warehouse:
#:
#:   ("tree", pattern)  match the source's own category path
#:   ("name", pattern)  match the product title
#:
#: The title form exists for Packaging and Safety, which have no source
#: category at all -- an earlier version pulled them from "Kitchen & Dining"
#: and "Automotive" and filled a warehouse's PPE shelf with car sun-shades and
#: vehicle horns. Searching titles for gloves, helmets and storage containers
#: finds fewer items but finds the right ones.
FROM_CATEGORY: dict[str, tuple[str, str]] = {
    "Networking": ("tree", r"Network Components"),
    "Electronics": ("tree", r"Mobiles & Accessories|Computers"),
    # Home Decor is deliberately absent: it is mostly showpieces and religious
    # figurines, and one of those as a warehouse's top-earning line reads as an
    # accident rather than a catalogue.
    "Furniture": ("tree", r"Home Furnishing|Furniture"),
    "Office Supplies": ("tree", r"Pens & Stationery"),
    "Packaging": (
        "name",
        r"(?i)\b(container|storage box|air ?tight|jar|canister|lunch box|"
        r"tiffin|organiser|organizer)\b",
    ),
    "Safety & PPE": (
        "name",
        # Word boundaries matter more here than anywhere else: without them
        # "lock" matched "clock" and put a wall clock on the safety shelf.
        r"(?i)\b(glove|gloves|helmet|goggle|goggles|face mask|safety|"
        r"protective|first aid|knee ?pad|tool ?kit|screwdriver|wrench|"
        r"plier|pliers|torch|extinguisher)\b",
    ),
}

#: Source categories a target may NOT take, applied after the match above.
#: Electronics draws from "Computers", and Network Components sits inside it --
#: so without this the Electronics shelf fills with routers while Networking,
#: which wants exactly those, competes for them.
NOT_FROM: dict[str, str] = {
    "Electronics": r"Network Components",
}

#: Product types, longest phrase first so "duvet cover" wins over "cover" and
#: "range extender" over "extender". This is what turns a 60-character listing
#: title into something a person can read in a table: the type is the only part
#: of the title that says what the thing IS.
TYPES = [
    # networking
    "wi-fi range extender",
    "range extender",
    "wifi repeater",
    "wi-fi router",
    "3g router",
    "router",
    "modem",
    "network switch",
    "access point",
    "wire connector",
    "charge controller",
    "wifi adapter",
    "usb adapter",
    # electronics
    "power bank",
    "pen drive",
    "hard disk",
    "memory card",
    "screen guard",
    "tempered glass",
    "back panel",
    "mobile skin",
    "phone holder",
    "socket holder",
    "camera lens",
    "earphone",
    "headphone",
    "headset",
    "bluetooth speaker",
    "speaker",
    "led light",
    "usb cable",
    "data cable",
    "charger",
    "keyboard",
    "mouse",
    "motherboard",
    "book cover",
    "flip cover",
    # Added after reading the output: without these, "Tucasa LG-186 Table
    # Lamp" matched only "table" and became "Tucasa Table", and a home
    # security camera matched nothing and fell back to its first three words.
    "security camera",
    "cctv camera",
    "web camera",
    "camera",
    "table lamp",
    "desk lamp",
    "lamp",
    "table fan",
    "usb fan",
    "fan",
    "wall clock",
    "clock",
    "photo frame",
    "extension board",
    "power strip",
    "trimmer",
    "iron",
    "back cover",
    "pouch",
    "phone case",
    "cable organizer",
    # furniture / furnishing
    "duvet cover",
    "cushion cover",
    "bed sheet",
    "bedsheet",
    "diwan set",
    "window curtain",
    "door curtain",
    "curtain",
    "mattress",
    "blanket",
    "carpet",
    "table runner",
    "runner",
    "dressing table",
    "coffee table",
    "study table",
    "desk chair",
    "office chair",
    "chair",
    "table",
    "bean bag",
    "wardrobe",
    "bookshelf",
    "shelf",
    "sofa",
    "single bed",
    "bed",
    "coaster set",
    "towel",
    "pillow cover",
    "apron",
    "kitchen linen",
    # The compounds below exist because "table" on its own is greedy: a set of
    # table napkins matched it and shipped as "Brown Table" with a photograph
    # of napkins. Longest-match wins, so naming the compound is the fix.
    "table mat",
    "table napkin",
    "table cover",
    "table cloth",
    "napkin",
    "sofa cover",
    "chair cover",
    "bed cover",
    "wall sticker",
    "wall decal",
    "door mat",
    "floor mat",
    "mat",
    "cushion",
    "curtain rod",
    "bed side table",
    # office
    "spiral notebook",
    "notebook",
    "diary",
    "ball pen",
    "pen",
    "pencil",
    "marker",
    "highlighter",
    "vacuum bottle",
    "water bottle",
    "bottle",
    "file folder",
    "sticky notes",
    "paper weight",
    # packaging / storage
    "lunch box",
    "storage box",
    "container",
    "jewel organizer",
    "organizer",
    "organiser",
    "jar",
    "canister",
    "tiffin",
    # safety
    "safety gloves",
    "gloves",
    "glove",
    "helmet lock",
    "helmet",
    "goggles",
    "face mask",
    "knee pad",
    "first aid kit",
]

#: Words worth keeping in front of the type because they distinguish two
#: otherwise identical rows. Anything else in the title is dropped.
QUALIFIERS = [
    "cotton",
    "silk",
    "polyester",
    "leather",
    "leatherette",
    "wooden",
    "wood",
    "plastic",
    "steel",
    "ceramic",
    "glass",
    "solid wood",
    "printed",
    "abstract",
    "floral",
    "striped",
    "magnetic",
    "wireless",
    "flexible",
    "portable",
    "rechargeable",
    "waterproof",
    "king",
    "queen",
    "single",
    "double",
    "black",
    "white",
    "blue",
    "red",
    "green",
    "purple",
    "orange",
    "brown",
    "grey",
    "gray",
    "pink",
    "yellow",
    "silver",
    "golden",
]

#: Nothing that would read badly on a projector in a lecture theatre.
_UNSUITABLE = re.compile(
    r"(?i)\b(bra|panty|panties|lingerie|nightwear|innerwear|thong|briefs|"
    r"shapewear|camisole|condom|intimate)\b"
)


def _first_image(cell: str) -> str | None:
    try:
        parsed = json.loads(cell)
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    except Exception:
        pass
    found = re.search(r'https?://[^\s",\]]+', str(cell))
    return found.group(0) if found else None


def _brandish(brand: str) -> str:
    """The brand, if it is one worth printing.

    Source brands include model codes, colour words and shop names forty
    characters long. A brand earns its place in a table cell only when it is
    short and looks like a name.
    """
    brand = re.sub(r"\s+", " ", str(brand or "")).strip()
    if not (2 <= len(brand) <= 14):
        return ""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9&.\- ]*", brand):
        return ""
    if re.search(r"\d{3,}", brand):
        return ""
    return brand


def _short_name(title: str, brand: str, category: str) -> str:
    """A listing title reduced to something readable in a table row.

    The source sells to shoppers, so a title carries everything a shopper might
    search for: brand, model code, colour, size, compatibility list. In a
    warehouse table none of that is the point -- the row has to say what the
    thing IS, at a glance, in a column a few centimetres wide.

    So: find the product TYPE, keep at most one distinguishing qualifier in
    front of it, and put the brand first only when the brand is short enough to
    be worth the space. "SANTOSH ROYAL FASHION Cotton Printed King sized Double
    Bedsheet" becomes "Cotton Bedsheet". Titles with no recognisable type fall
    back to their first few words, which is what a person skimming would keep
    anyway.
    """
    text = re.sub(r"\s+", " ", str(title)).strip()
    low = text.lower()

    # Whole words, longest first. Both halves of that are load-bearing:
    # a plain substring test matched "table" inside "portable" and turned a
    # portable charger into "ShadowFax Table", and taking the first listed
    # match rather than the longest turned an "Earphone Cable Organizer" into
    # "Earphone". The most specific phrase that fits is the right answer.
    kind = ""
    for candidate in sorted(TYPES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(candidate)}\b", low):
            kind = candidate
            break

    if kind:
        before = low[: low.index(kind)]
        qualifier = next(
            (q for q in QUALIFIERS if re.search(rf"\b{re.escape(q)}\b", before)), ""
        )
        core = f"{qualifier} {kind}".strip()
    else:
        # No known type in the title. Keep the opening words as they are,
        # model code and all: "D-Link DAP1320" IS the product name for a
        # router, and stripping the digits leaves "D-Link", which names the
        # manufacturer and not the thing on the shelf.
        core = " ".join(text.split()[:3])

    name = core if not kind else core.title()
    label = _brandish(brand)
    if label and label.lower() not in name.lower():
        candidate = f"{label} {name}"
        if len(candidate) <= 34:
            name = candidate

    name = re.sub(r"\s+", " ", name).strip(" -,")
    if len(name) > 38:
        name = name[:35].rsplit(" ", 1)[0] + "…"
    return name or str(title)[:30]


def load_source() -> pd.DataFrame:
    if not SOURCE.exists():
        raise SystemExit(f"Source catalogue not found: {SOURCE}")
    df = pd.read_csv(SOURCE, encoding="utf-8-sig", low_memory=False)
    df = df.dropna(subset=["product_name", "image", "product_category_tree"])
    df["url"] = df["image"].map(_first_image)
    df = df.dropna(subset=["url"])
    df = df[~df["product_name"].str.contains(_UNSUITABLE, na=False)]
    df = df.drop_duplicates(subset=["product_name"])

    # Quality ranking, best first. A named brand and a large source rendition
    # are what separate a listing that looks like a product from one that looks
    # like a phone snap, and the difference is visible at projector size.
    df["has_brand"] = df["brand"].notna() & df["brand"].astype(str).str.len().between(
        2, 28
    )
    df["big"] = df["url"].str.contains("800x800|1100x1100", regex=True)
    df["short"] = df["product_name"].str.len().between(12, 70)
    # A device beats an accessory for the same category. The top of the revenue
    # table is the first thing an audience reads, and a laptop there tells a
    # better story than a phone socket holder -- both are real products, but
    # only one looks like the flagship line of a business.
    df["is_device"] = df["product_name"].str.contains(
        r"(?i)\b(laptop|tablet|headphone|speaker|hard ?disk|pen ?drive|router|"
        r"keyboard|mouse|monitor|camera|smartwatch|printer|scanner|"
        r"chair|table|desk|sofa|wardrobe|shelf|mattress|cabinet)\b",
        regex=True,
        na=False,
    )
    df["score"] = (
        df["has_brand"].astype(int) * 4
        + df["is_device"].astype(int) * 3
        + df["big"].astype(int) * 2
        + df["short"].astype(int)
    )
    return df.sort_values("score", ascending=False)


def products() -> list[dict]:
    """Every TechNova product, richest first, so the best listings lead."""
    sql = text("""
        SELECT p.id::text AS id, p.sku, p.name AS old_name, p.category,
               COALESCE(p.abc_class, '-') AS abc_class,
               COALESCE(SUM(si.quantity * si.unit_price), 0)::numeric AS revenue
        FROM products p
        JOIN companies c ON c.id = p.company_id AND c.name = 'TechNova Industries'
        LEFT JOIN sale_items si ON si.product_id = p.id
        GROUP BY p.id, p.sku, p.name, p.category, p.abc_class
        ORDER BY revenue DESC
        """)
    db = SessionLocal()
    try:
        return [dict(r._mapping) for r in db.execute(sql)]
    finally:
        db.close()


def build_plan() -> list[dict]:
    source = load_source()
    rows = products()
    log.info("Products to re-stock: %d", len(rows))

    tree = source["product_category_tree"]
    title = source["product_name"]
    pools: dict[str, list[tuple[str, str, str]]] = {}
    for category, (form, pattern) in FROM_CATEGORY.items():
        column = tree if form == "tree" else title
        hit = source[column.str.contains(pattern, regex=True, na=False)]
        exclude = NOT_FROM.get(category)
        if exclude:
            hit = hit[
                ~tree.str.contains(exclude, regex=True, na=False).reindex(hit.index)
            ]
        # Interleaved by brand rather than taken in score order. Score order
        # put four "Aroma Comfort" curtains in the top eight, which reads as a
        # catalogue with one supplier rather than a business with a range.
        # Round-robin across brands keeps the quality ranking WITHIN each brand
        # while spreading them out.
        by_brand: dict[str, list] = {}
        for _, r in hit.iterrows():
            brand = str(r["brand"]) if r["has_brand"] else "-"
            by_brand.setdefault(brand, []).append(
                (r["product_name"], r["url"], brand if brand != "-" else "")
            )
        spread: list[tuple[str, str, str]] = []
        depth = 0
        while any(len(v) > depth for v in by_brand.values()):
            for items in by_brand.values():
                if len(items) > depth:
                    spread.append(items[depth])
            depth += 1
        pools[category] = spread
        log.info("  %-16s %5d candidates", category, len(pools[category]))

    taken: dict[str, int] = {}
    used_names: set[str] = set()
    plan: list[dict] = []
    for row in rows:
        pool = pools.get(row["category"]) or []
        entry = {
            "id": row["id"],
            "sku": row["sku"],
            "old_name": row["old_name"],
            "name": row["old_name"],
            "brand": "",
            "category": row["category"],
            "abc_class": row["abc_class"],
            "revenue": float(row["revenue"]),
            "image_url": None,
            "source_url": None,
        }
        index = taken.get(row["category"], 0)
        while (
            index < len(pool)
            and _short_name(pool[index][0], pool[index][2], row["category"])
            in used_names
        ):
            index += 1
        if index < len(pool):
            raw_name, url, brand = pool[index]
            taken[row["category"]] = index + 1
            name = _short_name(raw_name, brand, row["category"])
            used_names.add(name)
            entry["name"] = name
            entry["brand"] = brand
            entry["image_url"] = f"/catalogue/{row['sku']}.webp"
            entry["source_url"] = url
        else:
            log.warning("  ran out of candidates for %s", row["category"])
        plan.append(entry)
    return plan


def _fetch(entry: dict) -> tuple[dict, bool]:
    from PIL import Image

    destination = IMAGE_DIR / f"{entry['sku']}.webp"
    if destination.exists() and destination.stat().st_size > 0:
        return entry, True
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    for attempt in (1, 2, 3):
        try:
            request = urllib.request.Request(
                entry["source_url"], headers={"User-Agent": "Mozilla/5.0"}
            )
            raw = urllib.request.urlopen(request, timeout=30, context=context).read()
            image = Image.open(io.BytesIO(raw))
            image.thumbnail((THUMB_PX, THUMB_PX))
            image.convert("RGB").save(destination, "WEBP", quality=80, method=6)
            return entry, True
        except Exception as error:  # noqa: BLE001
            if attempt == 3:
                log.warning("  %s: %s", entry["sku"], str(error)[:60])
    return entry, False


def download(plan: list[dict]) -> list[dict]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [e for e in plan if e["source_url"]]
    log.info("\nDownloading %d images...", len(wanted))
    with ThreadPoolExecutor(max_workers=10) as pool:
        for entry, ok in pool.map(_fetch, wanted):
            if not ok:
                # A failed download means no picture, never a broken picture.
                entry["image_url"] = None
    got = sum(1 for e in plan if e["image_url"])
    total = sum(f.stat().st_size for f in IMAGE_DIR.glob("*.webp"))
    log.info(
        "  %d images · %.2f MB · %.0f KB average",
        got,
        total / 1e6,
        total / max(got, 1) / 1024,
    )
    return plan


def write_outputs(plan: list[dict]) -> None:
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["SKU", "Name", "Brand", "Category", "Revenue_Tier", "Revenue", "Image_URL"]
        )
        for row in plan:
            writer.writerow(
                [
                    row["sku"],
                    row["name"],
                    row["brand"],
                    row["category"],
                    row["abc_class"],
                    f"{row['revenue']:.2f}",
                    row["image_url"] or "",
                ]
            )
    log.info("Wrote %s and %s", PLAN.name, CSV_OUT.name)


def apply_plan() -> None:
    if not PLAN.exists():
        raise SystemExit("No plan found. Run --plan first.")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        for row in plan:
            db.execute(
                text(
                    "UPDATE products SET name = :name, image_url = :image "
                    "WHERE id = CAST(:id AS uuid)"
                ),
                {"name": row["name"], "image": row["image_url"], "id": row["id"]},
            )
        db.commit()
        log.info(
            "Updated %d products. Revenue, stock, ABC and history untouched.", len(plan)
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.plan:
        plan = download(build_plan())
        write_outputs(plan)
        illustrated = [p for p in plan if p["image_url"]]
        tiers: dict[str, int] = {}
        for row in illustrated:
            tiers[row["abc_class"]] = tiers.get(row["abc_class"], 0) + 1
        log.info("\nIllustrated by revenue tier: %s", dict(sorted(tiers.items())))
        log.info("Top earners now read as:")
        for row in plan[:8]:
            log.info(
                "  %-14s %-52s %14s",
                row["sku"],
                row["name"][:52],
                f"{row['revenue']:,.0f}",
            )
    elif args.apply:
        apply_plan()
    else:
        parser.error("choose --plan or --apply")


if __name__ == "__main__":
    main()
