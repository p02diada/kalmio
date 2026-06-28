from django.core.management.base import BaseCommand, CommandError

from charging.snapshots import ChargerSnapshotError, restore_charger_snapshot


DEFAULT_SNAPSHOT_PATH = ".dev-data/kalmio-chargers.postgis.dump"


class Command(BaseCommand):
    help = "Restore local authorized charger tables from a PostGIS snapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=DEFAULT_SNAPSHOT_PATH,
            help=f"Input dump path. Defaults to {DEFAULT_SNAPSHOT_PATH}.",
        )

    def handle(self, *args, **options):
        try:
            path = restore_charger_snapshot(options["path"])
        except ChargerSnapshotError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Restored charger snapshot from {path}"))
