from django.core.management.base import BaseCommand, CommandError

from charging.snapshots import ChargerSnapshotError, dump_charger_snapshot


DEFAULT_SNAPSHOT_PATH = ".dev-data/kalmio-chargers.postgis.dump"


class Command(BaseCommand):
    help = "Create a PostGIS snapshot of local authorized charger tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=DEFAULT_SNAPSHOT_PATH,
            help=f"Output dump path. Defaults to {DEFAULT_SNAPSHOT_PATH}.",
        )

    def handle(self, *args, **options):
        try:
            path = dump_charger_snapshot(options["path"])
        except ChargerSnapshotError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Wrote charger snapshot to {path}"))
