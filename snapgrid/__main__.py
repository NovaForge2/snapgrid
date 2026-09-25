# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Command line entry point.

    ./server.py            start it in the background and print the address
    ./server.py stop       stop it
    ./server.py status     is it running, and where
    ./server.py serve      run in the foreground instead, Ctrl+C to stop
    ./server.py encrypt    encrypt a secret for a plugin .env file

The port is chosen once and written next to the plugins, so stop and status
never have to go looking for it, and neither do you.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .api import make_server
from .config import Config, display_path
from .manifest import Registry
from .runner import Runner
from .scheduler import Scheduler
from .secrets_store import SecretError, encrypt, key_path, load_key
from .settings import load_settings
from .store import Store

START_TIMEOUT = 20.0

# Creation flag for systems with consoles: the interpreter is a console program,
# so unless it is told otherwise a background child gets a console window of its
# own, which appears and disappears and looks alarming. This asks for none at
# all. Detaching is not the right tool: it only stops the child inheriting ours,
# and a fresh one is then created for it.
CREATE_NO_WINDOW = 0x08000000


def quiet_run(command: list[str]):
    """Run a helper command without a console window flashing up."""
    extra = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(command, capture_output=True, text=True, check=False, **extra)


DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def no_plugins_hint(config: Config) -> str:
    """What to say when the folder is empty.

    Nothing is copied anywhere. The examples are a working plugins folder in
    their own right, so the answer to "show me what this does" is a command,
    not a file operation.
    """
    if not EXAMPLES_DIR.is_dir():
        return ""
    plugins = display_path(config.plugins_dir)
    examples = display_path(EXAMPLES_DIR)
    return (
        f"no plugins found in {plugins}/\n"
        f"\n"
        f"  see the examples:   ./server.py --dir {examples}\n"
        f"  start your own:     cp -r {examples}/hello-table {plugins}/my-plugin\n"
        f"                      then edit {plugins}/my-plugin/plugin.toml"
    )


def command_hint(config: Config, command: str) -> str:
    """How to type a command for *this* workspace, not the default one."""
    if config.plugins_dir == DEFAULT_PLUGINS_DIR.resolve():
        return f"./server.py {command}"
    return f"./server.py --dir {display_path(config.plugins_dir)} {command}"


def config_from(args: argparse.Namespace) -> Config:
    plugins_dir = Path(getattr(args, "dir", None) or DEFAULT_PLUGINS_DIR).expanduser()
    # A command line option beats snapgrid.toml, which beats the built-in default.
    settings = load_settings()
    port = getattr(args, "port", None)
    limit = getattr(args, "max_concurrent", None)
    return Config(
        plugins_dir=plugins_dir,
        data_dir=getattr(args, "data", None),
        host=getattr(args, "host", None) or "127.0.0.1",
        port=port if port is not None else settings["port"],
        max_concurrent=limit if limit is not None else settings["max_concurrent"],
    )


# ----- knowing whether a server is already running -----------------------

def read_state(config: Config) -> dict | None:
    try:
        return json.loads(config.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            return str(pid) in quiet_run(["tasklist", "/FI", f"PID eq {pid}", "/NH"]).stdout
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def pid_listening_on(port: int) -> int | None:
    """Which process holds this port, asked of the operating system.

    The pid written down can become unusable - a stale file, or a number this
    shell cannot see. The port is the more reliable handle, provided whatever
    holds it has already identified itself as snapgrid.
    """
    try:
        if os.name == "nt":
            output = quiet_run(["netstat", "-ano"]).stdout
            for line in output.splitlines():
                parts = line.split()
                if (len(parts) >= 5 and parts[0].upper() == "TCP"
                        and parts[1].endswith(f":{port}")
                        and parts[3].upper() == "LISTENING"):
                    return int(parts[4])
        else:
            output = quiet_run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"]).stdout
            found = output.split()
            if found:
                return int(found[0])
    except (OSError, ValueError):
        pass
    return None


def state_is_live(state: dict) -> bool:
    """Is the server this record describes still there?

    Asked two ways, because neither is reliable alone. A process id can be
    invisible: a shell may number processes differently from the system
    underneath it, and the tool for listing them may not be reachable. And a
    port can be answered by something else entirely. Either a live process id or
    a port answering as snapgrid means it is still running.
    """
    if process_alive(int(state.get("pid", 0))):
        return True
    host = state.get("host") or "127.0.0.1"
    port = int(state.get("port") or 0)
    return bool(port) and looks_like_snapgrid(host, port)


def running_state(config: Config) -> dict | None:
    """The state file only counts if that server is still there."""
    state = read_state(config)
    if state and state_is_live(state):
        return state
    if state:
        config.state_file.unlink(missing_ok=True)
    return None


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


def looks_like_snapgrid(host: str, port: int) -> bool:
    """Is the thing already on this port one of ours?"""
    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/api/plugins", headers={"X-Snapgrid": "1"}
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            return "plugins" in json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return False


def require_port(config: Config) -> None:
    """Insist on the port that was asked for.

    Moving to another port when this one is busy would mean the address
    changes under you, and an address you cannot bookmark is not much of an
    address. So this fails and says what to do instead.
    """
    if port_is_free(config.host, config.port):
        return

    where = f"http://{config.host}:{config.port}"
    if looks_like_snapgrid(config.host, config.port):
        raise SystemExit(
            f"snapgrid: something that looks like snapgrid is already at {where},\n"
            f"  started from a different folder, or left behind by an earlier run.\n"
            f"  Open it, or stop it, before starting this one."
        )
    raise SystemExit(
        f"snapgrid: port {config.port} is already in use by something else.\n"
        f"  Either stop it, or choose another port:\n"
        f"    ./server.py --port 8770\n"
        f"  To make the choice permanent, put it in {config.plugins_dir / 'snapgrid.toml'}:\n"
        f"    [server]\n"
        f"    port = 8770"
    )


# ----- commands ----------------------------------------------------------

def command_serve(args: argparse.Namespace) -> int:
    config = config_from(args)
    config.prepare()

    # Two servers on one folder would share the database and both schedule the
    # same plugins, so this is refused rather than made configurable. Run a
    # second one somewhere else with --dir.
    existing = running_state(config)
    if existing:
        print(
            f"snapgrid is already running at {existing['url']} (pid {existing['pid']}).\n"
            f"Use '{command_hint(config, 'stop')}' first, "
            f"or '{command_hint(config, 'status')}' to see it.",
            file=sys.stderr,
        )
        return 1

    require_port(config)


    store = Store(config.db_path)
    registry = Registry(config.plugins_dir)
    registry.scan()
    runner = Runner(store, registry, config)
    runner.start()
    scheduler = Scheduler(store, registry, runner)
    scheduler.start()
    httpd = make_server(config, store, registry, runner)

    url = f"http://{config.host}:{config.port}"
    config.state_file.write_text(
        json.dumps({"pid": os.getpid(), "port": config.port, "host": config.host,
                    "url": url, "started": time.time()}),
        encoding="utf-8",
    )

    print(f"snapgrid {__version__}")
    print(f"  plugins   {display_path(config.plugins_dir)}  ({len(registry.all())} found)")
    print(f"  data      {display_path(config.data_dir)}")
    print(f"  open      {url}")
    if os.name == "nt":
        print("  stop      Ctrl+C   (./server.py start runs it in the background)")
    else:
        print("  stop      Ctrl+C")
    if not registry.all():
        hint = no_plugins_hint(config)
        if hint:
            print()
            print(hint)
    sys.stdout.flush()

    # Respond to stop the same way as to Ctrl+C, so a backgrounded server
    # shuts its plugins down cleanly instead of being killed mid-run.
    def handle_term(_signum, _frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, handle_term)
    except (ValueError, AttributeError, OSError):
        pass

    if args.open:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        scheduler.stop()
        runner.stop()
        httpd.server_close()
        store.close()
        config.state_file.unlink(missing_ok=True)
    return 0


def command_start(args: argparse.Namespace) -> int:
    config = config_from(args)
    config.prepare()

    existing = running_state(config)
    if existing:
        print(f"already running at {existing['url']} (pid {existing['pid']})")
        if args.open:
            webbrowser.open(existing["url"])
        return 0

    command = [
        sys.executable, "-m", "snapgrid", "serve",
        "--dir", str(config.plugins_dir),
        "--data", str(config.data_dir),
        "--host", config.host,
        "--port", str(config.port),
        "--max-concurrent", str(config.max_concurrent),
    ]
    detached: dict = {}
    if os.name == "nt":
        detached["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        detached["start_new_session"] = True

    with config.log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n--- started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        child = subprocess.Popen(
            command, cwd=str(Path(__file__).resolve().parent.parent),
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, **detached,
        )

    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        state = running_state(config)
        if not state and child.poll() is not None:
            # It gave up already. Say why now rather than after the timeout.
            break
        if state:
            print(f"snapgrid is running in the background at {state['url']}")
            print(f"  stop   {command_hint(config, 'stop')}")
            print(f"  log    {display_path(config.log_file)}")
            registry = Registry(config.plugins_dir)
            registry.scan()
            if not registry.all():
                hint = no_plugins_hint(config)
                if hint:
                    print()
                    print(hint)
            if args.open:
                webbrowser.open(state["url"])
            return 0
        time.sleep(0.2)

    print("snapgrid did not start:", file=sys.stderr)
    try:
        lines = config.log_file.read_text(encoding="utf-8").splitlines()
        # Only what this attempt wrote, not the whole history of the log.
        for index in range(len(lines) - 1, -1, -1):
            if lines[index].startswith("--- started "):
                lines = lines[index + 1:]
                break
        for line in lines[-15:]:
            print(f"  {line}", file=sys.stderr)
    except OSError:
        pass
    return 1


def command_stop(args: argparse.Namespace) -> int:
    config = config_from(args)
    state = running_state(config)
    if not state:
        print("snapgrid is not running")
        return 0

    pid = int(state["pid"])
    if not process_alive(pid):
        # The record is unusable but something is still answering, so ask the
        # operating system who actually holds the port.
        holder = pid_listening_on(int(state.get("port") or 0))
        if holder:
            pid = holder

    def kill(force: bool) -> None:
        try:
            if os.name == "nt":
                # No signals here, so the platform's own tool does the work.
                # /T takes the children with it, and asking politely first buys
                # nothing.
                flags = ["/F", "/T"] if force else ["/T"]
                quiet_run(["taskkill", *flags, "/PID", str(pid)])
            else:
                os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    # Where there is no SIGTERM there is no graceful path, so go straight to
    # forcing it rather than waiting for a request that cannot arrive.
    kill(force=(os.name == "nt"))

    deadline = time.time() + 10
    while time.time() < deadline:
        if not state_is_live(state):
            config.state_file.unlink(missing_ok=True)
            print(f"stopped (was {state['url']})")
            return 0
        time.sleep(0.2)

    kill(force=True)
    for _ in range(25):
        if not state_is_live(state):
            config.state_file.unlink(missing_ok=True)
            print(f"stopped, after having to force it (pid {pid})")
            return 0
        time.sleep(0.2)

    # Say so rather than leaving a record that claims it is stopped, and give
    # the commands to finish the job. Nobody should have to go looking for
    # these while a process they did not want is still running.
    port = int(state.get("port") or 0)
    print(f"could not stop snapgrid at {state['url']} (pid {pid}). Kill it with:\n",
          file=sys.stderr)
    if os.name == "nt":
        print(f"  netstat -ano | grep {port}          # last column is the pid\n"
              f"  taskkill //F //T //PID <pid>\n"
              f"\n"
              f"  Some shells need the slashes doubled as shown. A shell's own kill\n"
              f"  command may not accept this process id, so prefer the one above.\n"
              f"  Ending it from the system's own process viewer works too.",
              file=sys.stderr)
    else:
        print(f"  lsof -ti tcp:{port} | xargs kill -9\n"
              f"\n"
              f"  or, if you know the pid:  kill -9 {pid}", file=sys.stderr)
    print(f"\nThen remove the stale record:\n"
          f"  rm -f {display_path(config.state_file)}", file=sys.stderr)
    return 1


def command_status(args: argparse.Namespace) -> int:
    config = config_from(args)
    state = running_state(config)
    if not state:
        print("snapgrid is not running")
        return 1
    started = time.strftime("%H:%M:%S", time.localtime(state.get("started", 0)))
    print(f"snapgrid is running at {state['url']}")
    print(f"  pid     {state['pid']}, since {started}")
    print(f"  plugins {display_path(config.plugins_dir)}")
    print(f"  log     {display_path(config.log_file)}")
    print(f"  stop    {command_hint(config, 'stop')}")
    return 0


def command_encrypt(args: argparse.Namespace) -> int:
    # Whether a key was just made or already existed is the thing someone
    # wants to know the first time they run this.
    was_there = key_path().exists()
    try:
        key = load_key(create=True)
    except SecretError as exc:
        print(f"snapgrid: {exc}", file=sys.stderr)
        return 1

    value = args.value
    if value is None:
        value = getpass.getpass("value to encrypt (not shown): ")
    if not value:
        print("snapgrid: nothing to encrypt", file=sys.stderr)
        return 1

    print()
    print("Put this line in the .env file of your plugin:")
    print()
    print(f"    SOME_NAME={encrypt(value, key)}")
    print()
    if was_there:
        print(f"Encrypted with the key already in {key_path()}.")
    else:
        print(f"A new key was generated for you: 32 random bytes, saved in {key_path()}.")
        print("You never type this key and never choose one yourself.")
    print("Back it up. Without it, values encrypted with it cannot be read back.")
    return 0


# ----- argument parsing --------------------------------------------------

def add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", help="the folder holding your plugins (default: ./plugins)")
    parser.add_argument("--data", help="where to keep the database and log (default: <dir>/.snapgrid)")


def add_server_arguments(parser: argparse.ArgumentParser) -> None:
    add_location_arguments(parser)
    parser.add_argument("--host", help="default: 127.0.0.1, this machine only")
    parser.add_argument("--port", type=int,
                        help="default: 8765, or [server] port in snapgrid.toml")
    parser.add_argument("--max-concurrent", type=int, help="how many plugins may run at once")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snapgrid", description="Put a script in a folder, get a table in your browser."
    )
    parser.add_argument("--version", action="version", version=f"snapgrid {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser(
        "start",
        help="run in the background" + ("" if os.name == "nt" else " (the default)"),
    )
    add_server_arguments(start)
    start.add_argument("--open", action="store_true", help="also open it in your browser")
    start.set_defaults(func=command_start)

    stop = subparsers.add_parser("stop", help="stop the background server")
    add_location_arguments(stop)
    stop.set_defaults(func=command_stop)

    status = subparsers.add_parser("status", help="show whether it is running, and where")
    add_location_arguments(status)
    status.set_defaults(func=command_status)

    serve = subparsers.add_parser(
        "serve",
        help="run in the foreground, Ctrl+C to stop"
             + (" (the default)" if os.name == "nt" else ""),
    )
    add_server_arguments(serve)
    serve.add_argument("--open", action="store_true", help="also open it in your browser")
    serve.set_defaults(func=command_serve)

    enc = subparsers.add_parser("encrypt", help="encrypt a secret for a plugin .env file")
    enc.add_argument("value", nargs="?", help="omit this to be prompted without echo")
    enc.set_defaults(func=command_encrypt)

    return parser


COMMANDS = {"start", "stop", "status", "serve", "encrypt"}

# What running it with no command does. Where a background server can be
# managed reliably that is "start": run detached and hand the terminal back.
# Where it cannot, it is "serve": run here, Ctrl+C to stop.
#
# Background mode has to detach a process and later find and kill it again, and
# without signals every part of that is less dependable - process ids may not be
# the numbers the shell shows, kill may not accept them, and a server that will
# not stop has to be ended some other way. A foreground server has none of those
# problems: it is in front of you, and Ctrl+C ends it. "start" remains available
# either way.
DEFAULT_COMMAND = "serve" if os.name == "nt" else "start"
# Flags that swallow the next word, so a folder called "stop" is not mistaken
# for a command.
VALUE_FLAGS = {"--dir", "--data", "--host", "--port", "--max-concurrent"}


def normalise(argv: list[str]) -> list[str]:
    """Allow the command anywhere, and default to starting in the background.

    argparse wants the command first, but people write
    "./server.py --dir somewhere status", and running it with no command at all
    should do the thing you nearly always want.
    """
    if argv and argv[0] in ("-h", "--help", "--version"):
        return argv

    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if token in VALUE_FLAGS:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if token in COMMANDS:
            return [token] + argv[:index] + argv[index + 1:]
        break  # a positional that is not a command, so leave it alone
    return [DEFAULT_COMMAND] + argv


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = normalise(list(sys.argv[1:] if argv is None else argv))
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args([DEFAULT_COMMAND])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
