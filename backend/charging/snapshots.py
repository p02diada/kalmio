from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from django.apps import apps
from django.conf import settings
from django.db import connection


class ChargerSnapshotError(RuntimeError):
    pass


TRANSACTION_TIMEOUT_ERROR = 'unrecognized configuration parameter "transaction_timeout"'
@dataclass(frozen=True)
class PgCommand:
    args: list[str]
    env: dict[str, str]

    def display(self) -> str:
        return " ".join(shlex.quote(part) for part in self.args)


def charging_table_names() -> list[str]:
    tables = [model._meta.db_table for model in apps.get_app_config("charging").get_models()]
    return sorted(tables)


def dump_charger_snapshot(path: str | Path, *, runner=subprocess.run) -> Path:
    ensure_postgis_connection()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = build_pg_dump_command(destination, charging_table_names())
    run_pg_command(command, runner=runner)
    return destination


def restore_charger_snapshot(path: str | Path, *, runner=subprocess.run) -> Path:
    ensure_postgis_connection()
    source = Path(path)
    if not source.exists():
        raise ChargerSnapshotError(f"No existe el snapshot: {source}")

    truncate_charging_tables(charging_table_names())
    command = build_pg_restore_command(source)
    run_pg_command(command, runner=runner)
    return source


def ensure_postgis_connection() -> None:
    engine = connection.settings_dict.get("ENGINE", "")
    if "postgis" not in engine:
        raise ChargerSnapshotError("Los snapshots de cargadores requieren PostGIS.")


def build_pg_dump_command(path: Path, tables: Sequence[str]) -> PgCommand:
    db = database_connection_settings()
    args = [
        "pg_dump",
        "--format=custom",
        "--data-only",
        "--no-owner",
        "--no-acl",
        "--file",
        str(path),
        "--dbname",
        db["NAME"],
        "--username",
        db["USER"],
        "--host",
        db["HOST"],
        "--port",
        db["PORT"],
    ]
    for table in tables:
        args.extend(["--table", table])
    return PgCommand(args=args, env=pg_env(db))


def build_pg_restore_command(path: Path) -> PgCommand:
    db = database_connection_settings()
    args = [
        "pg_restore",
        "--data-only",
        "--no-owner",
        "--no-acl",
        "--dbname",
        db["NAME"],
        "--username",
        db["USER"],
        "--host",
        db["HOST"],
        "--port",
        db["PORT"],
        str(path),
    ]
    return PgCommand(args=args, env=pg_env(db))


def database_connection_settings() -> dict[str, str]:
    settings = connection.settings_dict
    return {
        "NAME": str(settings.get("NAME") or ""),
        "USER": str(settings.get("USER") or ""),
        "PASSWORD": str(settings.get("PASSWORD") or ""),
        "HOST": str(settings.get("HOST") or "localhost"),
        "PORT": str(settings.get("PORT") or "5432"),
    }


def pg_env(db: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = db["PASSWORD"]
    return env


def truncate_charging_tables(tables: Sequence[str]) -> None:
    if not tables:
        return
    quoted = ", ".join(connection.ops.quote_name(table) for table in tables)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")


def run_pg_command(command: PgCommand, *, runner=subprocess.run) -> None:
    try:
        completed = runner(command.args, env=command.env, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        binary = command.args[0]
        if binary in {"pg_dump", "pg_restore"}:
            run_pg_command_through_docker(command)
            return
        raise ChargerSnapshotError(f"No encuentro `{binary}`. Usa el contenedor Docker PostGIS.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        if command.args[0] == "pg_restore" and is_ignorable_pg_restore_transaction_timeout(detail):
            return
        raise ChargerSnapshotError(f"Falló `{command.display()}`: {detail}") from exc
    if getattr(completed, "stderr", ""):
        # pg tools often emit harmless notices on stderr; keep the command result explicit for callers.
        return


def is_ignorable_pg_restore_transaction_timeout(detail: str) -> bool:
    return (
        TRANSACTION_TIMEOUT_ERROR in detail
        and "pg_restore: warning: errors ignored on restore: 1" in detail
        and detail.count("pg_restore: error:") == 1
    )


def run_pg_command_through_docker(command: PgCommand) -> None:
    binary = command.args[0]
    compose_file = Path(settings.BASE_DIR).parent / "docker-compose.yml"
    if not compose_file.exists():
        raise ChargerSnapshotError(
            f"No encuentro `{binary}` ni {compose_file}. Usa el contenedor Docker PostGIS."
        )

    docker_args, stdout_file, stdin_file = docker_compose_pg_args(command, compose_file)
    try:
        if stdout_file:
            with stdout_file.open("wb") as output:
                subprocess.run(docker_args, check=True, stdout=output, stderr=subprocess.PIPE)
        elif stdin_file:
            with stdin_file.open("rb") as input_file:
                subprocess.run(docker_args, check=True, stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            subprocess.run(docker_args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise ChargerSnapshotError(
            f"No encuentro `{binary}` ni `docker`. Usa el contenedor Docker PostGIS."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or b"").decode(errors="replace").strip()
        raise ChargerSnapshotError(f"Falló fallback Docker para `{binary}`: {detail}") from exc


def docker_compose_pg_args(command: PgCommand, compose_file: Path) -> tuple[list[str], Path | None, Path | None]:
    args = list(command.args)
    binary = args.pop(0)
    stdout_file: Path | None = None
    stdin_file: Path | None = None

    if binary == "pg_dump":
        output_index = args.index("--file")
        stdout_file = Path(args[output_index + 1])
        del args[output_index : output_index + 2]
    elif binary == "pg_restore":
        stdin_file = Path(args.pop())

    docker_args = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "exec",
        "-T",
    ]
    password = command.env.get("PGPASSWORD")
    if password:
        docker_args.extend(["-e", f"PGPASSWORD={password}"])
    docker_args.extend(["db", binary, *args])
    return docker_args, stdout_file, stdin_file
