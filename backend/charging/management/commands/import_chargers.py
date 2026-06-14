from django.core.management.base import BaseCommand, CommandError

from charging.importers import ChargerImportError, import_chargers, validate_charger_file


class Command(BaseCommand):
    help = "Import authorized charger data from CSV or JSON. Mock/sample records are rejected."

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV or JSON file with authorized charger data.")
        parser.add_argument(
            "--replace-source",
            action="store_true",
            help="Delete existing stations for the imported source name(s) before importing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate the file and print counts without writing to the database.",
        )

    def handle(self, *args, **options):
        try:
            if options["dry_run"]:
                result = validate_charger_file(options["path"])
            else:
                result = import_chargers(options["path"], replace_source=options["replace_source"])
        except ChargerImportError as exc:
            raise CommandError(str(exc)) from exc

        action = "Validated" if options["dry_run"] else "Imported"
        suffix = " No database changes were made." if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {result.stations} stations, {result.evses} EVSEs, {result.connectors} connectors.{suffix}"
            )
        )
