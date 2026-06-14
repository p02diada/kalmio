from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from charging.importers import ChargerImportError, import_chargers, validate_records
from charging.reve_dev import (
    REVE_SOURCE_NAME,
    SPAIN_BBOX,
    ReveDevScrapeError,
    fetch_reve_locations,
    reve_locations_to_charger_records,
)


class Command(BaseCommand):
    help = "Scrape REVE public map data for local development only and write import_chargers-compatible JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(settings.BASE_DIR / ".dev-data" / "reve-chargers.json"),
            help="Destination JSON file. Defaults to backend/.dev-data/reve-chargers.json.",
        )
        parser.add_argument(
            "--cache-dir",
            default=str(settings.BASE_DIR / ".dev-data" / "reve-pages"),
            help="Directory for cached REVE location pages. Defaults to backend/.dev-data/reve-pages.",
        )
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Build the output only from cached REVE pages. Fails at the first missing page.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=None,
            help="Limit REVE pagination for smoke tests. Omit to fetch the full Spain bounding box.",
        )
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=1.0,
            help="Delay between REVE page requests.",
        )
        parser.add_argument(
            "--timeout-seconds",
            type=float,
            default=30,
            help="HTTP timeout for each REVE request.",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=8,
            help="Maximum retries for transient REVE HTTP/network failures.",
        )
        parser.add_argument(
            "--retry-seconds",
            type=float,
            default=60,
            help="Base wait before retrying after a transient REVE HTTP/network failure.",
        )
        parser.add_argument(
            "--bbox",
            nargs=4,
            type=float,
            metavar=("LAT_NE", "LON_NE", "LAT_SW", "LON_SW"),
            help="Override bounding box. Defaults to mainland Spain plus Balearic coverage.",
        )
        parser.add_argument(
            "--import",
            dest="import_to_db",
            action="store_true",
            help="Import the generated file into the local database after validation.",
        )
        parser.add_argument(
            "--replace-source",
            action="store_true",
            help=f"When used with --import, replace existing stations from '{REVE_SOURCE_NAME}'.",
        )

    def handle(self, *args, **options):
        ensure_dev_only()
        bbox = bbox_from_options(options["bbox"])

        try:
            locations = fetch_reve_locations(
                bbox=bbox,
                max_pages=options["max_pages"],
                delay_seconds=options["delay_seconds"],
                timeout_seconds=options["timeout_seconds"],
                max_retries=options["max_retries"],
                retry_seconds=options["retry_seconds"],
                cache_dir=options["cache_dir"],
                offline=options["offline"],
                progress_callback=self.progress_callback(options["verbosity"]),
            )
            records = reve_locations_to_charger_records(locations)
            validate_records(records)
        except (ReveDevScrapeError, ChargerImportError) as exc:
            raise CommandError(str(exc)) from exc

        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"stations": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(records)} connector records from {len(locations)} REVE locations to {output_path}."
            )
        )

        if options["import_to_db"]:
            try:
                result = import_chargers(output_path, replace_source=options["replace_source"])
            except ChargerImportError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"Imported {result.stations} stations, {result.evses} EVSEs, {result.connectors} connectors."
                )
            )

    def progress_callback(self, verbosity: int):
        def report(page):
            if verbosity <= 0:
                return
            if page.page == 1 or page.page % 25 == 0 or page.next_page is None:
                total_pages = page.total_pages or "?"
                total_count = page.total_count or "?"
                self.stdout.write(f"Fetched REVE page {page.page}/{total_pages} ({total_count} locations).")

        return report


def ensure_dev_only() -> None:
    if settings.DEBUG:
        return
    if os.getenv("KALMIO_ALLOW_REVE_DEV_SCRAPE") == "1":
        return
    raise CommandError(
        "scrape_reve_dev is disabled when DEBUG=false. "
        "Set KALMIO_ALLOW_REVE_DEV_SCRAPE=1 only for an isolated non-production environment."
    )


def bbox_from_options(values: list[float] | None) -> dict[str, float]:
    if not values:
        return SPAIN_BBOX
    lat_ne, lon_ne, lat_sw, lon_sw = values
    return {
        "latitude_ne": lat_ne,
        "longitude_ne": lon_ne,
        "latitude_sw": lat_sw,
        "longitude_sw": lon_sw,
        "zoom": 6,
    }
