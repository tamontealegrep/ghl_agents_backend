"""Starts a company's backend on this machine and exposes it through an ngrok tunnel.

Use it to receive GoHighLevel webhooks while developing::

    python scripts/dev_tunnel.py --company family_aims

Reads ``companies/<company>/.env``: ``HOST``, ``PORT``, ``NGROK_TOKEN``, ``NGROK_DOMAIN`` and ``NGROK_KILL_EXISTING``.
The backend runs with the company's ``bundles/`` folder (no Docker). Needs the ``ngrok`` executable in the PATH.
Stopping the tunnel (Ctrl+C) also stops the backend this script started.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devenv  # noqa: E402

_TRUE = {"1", "true", "yes"}


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    """Waits until a TCP port accepts connections.

    Args:
        host: Host to probe.
        port: Port to probe.
        timeout: Seconds to wait.

    Returns:
        True when the port answered in time.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.3)
    return False


def kill_local_ngrok() -> bool:
    """Tries to stop local ngrok processes (best effort).

    Returns:
        True when the kill command succeeded.
    """
    command = ["taskkill", "/F", "/IM", "ngrok.exe"] if os.name == "nt" else ["pkill", "-f", "^ngrok( .*)?$"]
    try:
        return subprocess.run(command, text=True, capture_output=True).returncode == 0
    except OSError:
        return False


def open_tunnel(domain: str, port: int, kill_existing: bool) -> None:
    """Opens the ngrok tunnel and blocks until it closes.

    Args:
        domain: Reserved ngrok domain.
        port: Local port to expose.
        kill_existing: Retry once after stopping local ngrok when the domain is already online.

    Raises:
        subprocess.CalledProcessError: ngrok failed.
    """
    command = ["ngrok", "http", f"--domain={domain}", "--pooling-enabled", str(port)]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0:
        return
    stderr = result.stderr or ""
    if "ERR_NGROK_334" in stderr and kill_existing and kill_local_ngrok():
        time.sleep(1.0)
        retry = subprocess.run(command, text=True, capture_output=True)
        if retry.returncode == 0:
            return
        stderr = retry.stderr or stderr
    if "ERR_NGROK_334" in stderr:
        stderr += "\nThe domain is already online: stop that endpoint, start every client with --pooling-enabled, or set NGROK_KILL_EXISTING=true."
    raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--company", required=True, help="Folder under companies/.")
    parser.add_argument("--env-file", type=Path, help="Explicit .env file (overrides the company's).")
    args = parser.parse_args(argv)

    try:
        env = devenv.load_environment(args.company, args.env_file)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    domain = env.get("NGROK_DOMAIN", "").strip()
    if not domain:
        print("ERROR: NGROK_DOMAIN is empty in the .env", file=sys.stderr)
        return 2
    host = env.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(env.get("PORT", "8010") or 8010)
    probe = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    bundles = devenv.BACKEND_ROOT / "companies" / args.company / "bundles"
    server_env = {**env, "AGENTS_DIR": str(bundles), "HOST": host, "PORT": str(port)}

    print(f"Starting the {args.company} backend on http://{host}:{port} ...")
    server = subprocess.Popen([sys.executable, "-m", "agent_backend"], cwd=devenv.BACKEND_ROOT, env=server_env)
    try:
        if not wait_for_port(probe, port):
            print("ERROR: the backend did not answer in time.", file=sys.stderr)
            return 1
        if env.get("NGROK_TOKEN", "").strip():
            subprocess.run(["ngrok", "config", "add-authtoken", env["NGROK_TOKEN"].strip()], check=True)
        print(f"Tunnel: https://{domain} -> http://127.0.0.1:{port}")
        open_tunnel(domain, port, env.get("NGROK_KILL_EXISTING", "").strip().lower() in _TRUE)
        return 0
    except FileNotFoundError:
        print("ERROR: the 'ngrok' executable was not found in the PATH.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
