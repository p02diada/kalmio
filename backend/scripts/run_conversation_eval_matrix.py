#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(api_base: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{api_base}/api/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Backend did not become ready at {api_base}: {last_error}")


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def run_eval(
    *,
    agent_mode: str,
    model: str,
    base_url: str | None,
    api_key_env: str,
    label: str,
    dataset: str,
    case_from: int | None,
    case_to: int | None,
    repeat: int,
    max_concurrency: int,
    logfire: bool,
    output_dir: Path,
    startup_timeout: float,
    request_timeout: int,
    case_timeout: int,
) -> Path:
    port = free_port()
    api_base = f"http://127.0.0.1:{port}"
    trace_file = output_dir / f"{label}-trace.jsonl"
    output_file = output_dir / f"{label}.json"
    markdown_file = output_dir / f"{label}.md"
    env = os.environ.copy()
    api_key = env.get(api_key_env) or env.get("KALMIO_DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    env.update(
        {
            "KALMIO_CONVERSATION_AGENT_MODE": agent_mode,
            "KALMIO_CONVERSATION_AGENT_RUNTIME": "pydantic_ai",
            "KALMIO_DEEPSEEK_MODEL": model,
            "KALMIO_DEEPSEEK_API_KEY": api_key or "",
            "KALMIO_AGENT_TRACE_ENABLED": "true",
            "KALMIO_AGENT_TRACE_INCLUDE_PAYLOADS": "false",
            "KALMIO_AGENT_TRACE_FILE": str(trace_file),
            "KALMIO_ROUTE_CONVERSATION_THROTTLE_LIMIT": "1000",
            "KALMIO_ROUTING_READINESS_CHECK": env.get("KALMIO_ROUTING_READINESS_CHECK", "false"),
        }
    )
    if base_url:
        env["KALMIO_DEEPSEEK_BASE_URL"] = base_url
    trace_file.unlink(missing_ok=True)
    output_file.unlink(missing_ok=True)
    markdown_file.unlink(missing_ok=True)

    server = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_ready(api_base, startup_timeout)
        command = [
            sys.executable,
            "scripts/run_conversation_evals.py",
            "--api-base",
            api_base,
            "--dataset",
            dataset,
            "--label",
            label,
            "--trace-file",
            str(trace_file),
            "--output",
            str(output_file),
            "--markdown-output",
            str(markdown_file),
            "--repeat",
            str(repeat),
            "--max-concurrency",
            str(max_concurrency),
            "--request-timeout",
            str(request_timeout),
            "--case-timeout",
            str(case_timeout),
        ]
        if logfire:
            command.append("--logfire")
        if case_from is not None:
            command.extend(["--from", str(case_from)])
        if case_to is not None:
            command.extend(["--to", str(case_to)])
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0 and not output_file.exists():
            raise RuntimeError(f"{label} eval failed with exit code {result.returncode}.")
    finally:
        if server.poll() not in (None, 0):
            output = server.stdout.read() if server.stdout is not None else ""
            if output:
                print(output, file=sys.stderr)
        terminate_process(server)
    return output_file


def require_api_key(api_key_env: str) -> None:
    if os.getenv(api_key_env) or os.getenv("KALMIO_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY"):
        return
    raise SystemExit(f"{api_key_env}, KALMIO_DEEPSEEK_API_KEY, or DEEPSEEK_API_KEY is required to run eval matrix.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Kalmio Pydantic Evals across agent modes and OpenAI-compatible models."
    )
    parser.add_argument("--dataset", choices=["outcome"], default="outcome")
    parser.add_argument("--agent-modes", default="deepseek", help="Comma-separated agent modes.")
    parser.add_argument("--models", default="deepseek-v4-pro", help="Comma-separated OpenAI-compatible models.")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL override.")
    parser.add_argument("--api-key-env", default="KALMIO_DEEPSEEK_API_KEY", help="Environment variable containing the API key.")
    parser.add_argument("--from", dest="case_from", type=int)
    parser.add_argument("--to", dest="case_to", type=int)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--logfire", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("../reports/conversation-eval-matrix"))
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--request-timeout", type=int, default=180)
    parser.add_argument("--case-timeout", type=int, default=300)
    parser.add_argument("--skip-key-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_key_check:
        require_api_key(args.api_key_env)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for agent_mode in [item.strip() for item in args.agent_modes.split(",") if item.strip()]:
        for model in [item.strip() for item in args.models.split(",") if item.strip()]:
            label = f"{agent_mode}-{model}-{args.dataset}"
            print(f"==> running {label}")
            outputs.append(
                run_eval(
                    agent_mode=agent_mode,
                    model=model,
                    base_url=args.base_url,
                    api_key_env=args.api_key_env,
                    label=label,
                    dataset=args.dataset,
                    case_from=args.case_from,
                    case_to=args.case_to,
                    repeat=args.repeat,
                    max_concurrency=args.max_concurrency,
                    logfire=args.logfire,
                    output_dir=args.output_dir,
                    startup_timeout=args.startup_timeout,
                    request_timeout=args.request_timeout,
                    case_timeout=args.case_timeout,
                )
            )
    print("outputs:")
    for output in outputs:
        print(f"- {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
