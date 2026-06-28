from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from vehicles.iternio import (
    ITERNIO_DEFAULT_BASE_URL,
    IternioVehicleImportError,
    fetch_iternio_vehicle_catalog,
    import_iternio_vehicle_catalog,
    validate_catalog_payload,
)


DEFAULT_COUNTRY_CODE3 = "ESP"
DEFAULT_MIN_PROFILES = 500


class Command(BaseCommand):
    help = "Synchronize the production vehicle profile catalog from Iternio/ABRP."
    requires_system_checks = []
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("--api-key", help="Iternio API key. Defaults to ITERNIO_API_KEY.")
        parser.add_argument("--base-url", default=ITERNIO_DEFAULT_BASE_URL, help="Iternio API base URL.")
        parser.add_argument(
            "--country-code3",
            default=os.getenv("KALMIO_VEHICLE_PROFILE_SYNC_COUNTRY_CODE3", DEFAULT_COUNTRY_CODE3),
            help="ISO 3166-1 alpha-3 country filter. Defaults to ESP.",
        )
        parser.add_argument(
            "--min-profiles",
            type=int,
            default=int(os.getenv("KALMIO_VEHICLE_PROFILE_SYNC_MIN_PROFILES", str(DEFAULT_MIN_PROFILES))),
            help="Abort without replacing data if the fetched catalog has fewer profiles.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and validate the catalog without writing to the database.",
        )

    def handle(self, *args, **options):
        api_key = (options["api_key"] or os.getenv("ITERNIO_API_KEY") or "").strip()
        if not api_key:
            raise CommandError(
                "ITERNIO_API_KEY is required. Use a Kalmio-issued Iternio/ABRP key; "
                "do not use credentials embedded in the ABRP web client."
            )

        min_profiles = options["min_profiles"]
        if min_profiles < 1:
            raise CommandError("--min-profiles must be greater than zero.")

        try:
            payload = fetch_iternio_vehicle_catalog(
                api_key=api_key,
                base_url=options["base_url"],
                country_code3=options["country_code3"],
            )
            validate_catalog_payload(payload)
            vehicle_count = len(payload["vehicles"])
            if vehicle_count < min_profiles:
                raise IternioVehicleImportError(
                    f"Refusing to replace vehicle profiles: fetched {vehicle_count}, "
                    f"below minimum {min_profiles}."
                )

            if options["dry_run"]:
                result = None
            else:
                result = import_iternio_vehicle_catalog(
                    payload,
                    base_url=options["base_url"],
                    replace=True,
                )
        except IternioVehicleImportError as exc:
            raise CommandError(str(exc)) from exc

        options_count = len(payload.get("options") or [])
        display_count = len(payload.get("display") or [])
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validated weekly sync for {vehicle_count} vehicle profiles, "
                    f"{options_count} option groups, {display_count} display groups. "
                    "No database changes were made."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced {result.vehicles} vehicle profiles, {result.options} option groups, "
                f"{result.display_groups} display groups."
            )
        )
