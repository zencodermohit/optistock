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

#: Which source categories may fill each OptiStock category. Chosen so the
#: leading SKU segment stays true: ELEC draws from electronics, NETW from
#: actual network hardware -- which is the one category where this source is
#: genuinely excellent, being full of real Netgear, D-Link and TP-Link routers.
FROM_CATEGORY: dict[str, str] = {
    "Networking": r"Network Components",
    "Electronics": r"Mobiles & Accessories|Computers",
    # Home Decor is deliberately NOT here. It is mostly showpieces and
    # religious figurines, and "Eight Armed Goddess Sherawali Maa Showpiece"
    # as the top-earning line of a warehouse business reads as an accident.
    "Furniture": r"Home Furnishing|Furniture",
    "Office Supplies": r"Pens & Stationery|School Supplies",
    "Packaging": r"Bags, Wallets & Belts|Kitchen & Dining",
    "Safety & PPE": r"Tools & Hardware|Automotive",
}

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


def _tidy(name: str) -> str:
    """Trim a listing title to something that fits a table cell.

    Source titles carry the entire listing -- colour, pack size, compatibility
    list. Cut at the first separator, then cap, because the cell this lands in
    is a good deal narrower than the 255 characters the column allows.
    """
    name = re.sub(r"\s+", " ", str(name)).strip()
    name = re.split(r"\s+[-–|(]\s+", name)[0].strip()
    if len(name) > 58:
        name = name[:55].rsplit(" ", 1)[0].rstrip(",") + "…"
    return name


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
        r"(?i)(laptop|tablet|headphone|speaker|hard ?disk|pen ?drive|router|"
        r"keyboard|mouse|monitor|camera|smartwatch|printer|scanner|"
        r"chair|table|desk|sofa|wardrobe|shelf|mattress|cabinet)",
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
    pools: dict[str, list[tuple[str, str, str]]] = {}
    for category, pattern in FROM_CATEGORY.items():
        hit = source[tree.str.contains(pattern, regex=True, na=False)]
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
        while index < len(pool) and _tidy(pool[index][0]) in used_names:
            index += 1
        if index < len(pool):
            raw_name, url, brand = pool[index]
            taken[row["category"]] = index + 1
            name = _tidy(raw_name)
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
