#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""Which program is listening on which port, and the command that ends it.

The question this answers is "what has got port 8080, and what do I type to
make it let go". Every row carries the pid and the whole command to end that
process, ready to copy - written for the machine it is running on, so there is
nothing to translate at the moment you are in a hurry.

**Nothing is killed here.** A plugin reports; it does not act. The command is
text in a cell and you are the one who runs it, having first read what it is
you are about to end.

There is no way to ask Python which process holds a socket it does not own, so
this reads whatever the machine already has. It tries three tools in turn
rather than deciding by platform name: lsof is the best answer and is missing
from plenty of Linux images, ss is on modern Linux, netstat is what Windows
has. Which one answered is written to the log.
"""

import csv
import locale
import os
import re
import shutil
import subprocess
import sys

COLUMNS = ["listener", "port", "pid", "user", "program", "kill", "command"]
TIMEOUT = 20

def on_windows() -> bool:
    """Windows, including a Python there that calls itself something else.

    A plain python.exe says `os.name == "nt"`, but the Python a shell like Git
    Bash may put first on PATH comes from MSYS or Cygwin and says `posix`
    while the machine underneath it is still Windows - with Windows pids,
    taskkill rather than kill, and no ps worth asking.
    """
    return os.name == "nt" or sys.platform.startswith(("cygwin", "msys"))


def kill_command(pids: list[str]) -> str:
    """How this machine ends these processes, as a line to copy.

    The plugin says it rather than leaving the reader to know, because a table
    of pids without it is half an answer - and the missing half is different
    on every machine.

    taskkill wants its own /PID before each number: `taskkill /F /PID 990 991`
    is not a command that ends two processes, it is a command that fails.
    """
    if not pids:
        return ""
    if on_windows():
        return "taskkill /F " + " ".join(f"/PID {pid}" for pid in pids)
    return "kill -9 " + " ".join(pids)


def two_byte_encoding(raw: bytes) -> str | None:
    """'utf-16-le' or 'utf-16-be' when these bytes are that, else None.

    wmic writes UTF-16 when its output is a pipe rather than a console, and
    this is always a pipe. Decoded with a single byte encoding that happens
    to accept every byte - which cp1252 and cp1251 both do - it does not
    raise. It comes out as C\x00o\x00m\x00m\x00... instead, and every
    comparison against it quietly fails. The table then loses the whole
    column while the run reports success, which is the worst way for this
    to go wrong: nothing to see in the log, and a plausible empty cell.

    The BOM settles it when there is one. Without it, a zero after most
    letters is not something single byte text does.
    """
    if raw[:2] == b"\xff\xfe":
        return "utf-16-le"
    if raw[:2] == b"\xfe\xff":
        return "utf-16-be"
    sample = raw[:400]
    if not sample or sample.count(0) * 3 <= len(sample):
        return None
    # Which half of each pair is the zero says which way round it is.
    return "utf-16-le" if sample[1:2] == b"\x00" else "utf-16-be"


def decode(raw: bytes) -> str:
    """Bytes from a console tool, as text, never raising.

    Everything this reads - addresses, pids, program names - is ASCII or
    close to it. A character that does not survive becomes a replacement
    rather than an exception, because losing an accent in a program name is
    nothing and losing the whole table is not.
    """
    if isinstance(raw, str):            # a stand-in in the tests
        return raw
    wide = two_byte_encoding(raw)
    if wide:
        return raw.decode(wide, "replace").lstrip("\ufeff")
    for encoding in (locale.getpreferredencoding(False), "utf-8"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def found(program: str) -> str | None:
    """Where this program is, if it is anywhere.

    shutil.which appends the `.exe` only when Python believes it is running
    on Windows, and the Python a shell like Git Bash may be using does not
    believe that. Without the second look, wmic and powershell appear to be
    missing on precisely the machine that needs them.
    """
    where = shutil.which(program)
    if where is None and on_windows():
        where = shutil.which(program + ".exe")
    return where


def run(command: list[str], nothing_found: tuple[int, ...] = ()) -> str | None:
    """A helper's output, or None when it could not be run.

    None and "" are different answers and the difference matters: a tool that
    is not installed has told you nothing, while a tool that ran and printed
    nothing has told you there is nothing. Returning "" for both would make a
    machine with no listeners look like a machine with no lsof.

    A non-zero exit is a failure, including being killed by a signal and
    including a run that printed something first - half a table published as
    a whole one is the worse of the two outcomes. `nothing_found` lists the
    exit codes that mean "ran, matched nothing", which is lsof's 1.
    """
    name, where = command[0], found(command[0])
    if not where:
        return None
    # The resolved path, not the bare name: a name that only matched with an
    # .exe added would not start again without it.
    command = [where, *command[1:]]
    try:
        # Bytes, not text. text=True decodes with the locale's encoding and
        # refuses anything it does not recognise - and a console tool on a
        # localised Windows writes in the OEM code page, which is not that
        # one. A single byte of a translated word would end the run with a
        # decoding error, for a word this does not even read.
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return None

    out, err = decode(done.stdout), decode(done.stderr)
    if done.returncode != 0:
        if done.returncode in nothing_found and not err.strip():
            return out                  # it ran and matched nothing
        complaint = err.strip().splitlines()
        print(f"{name}: exit {done.returncode}"
              + (f": {complaint[0]}" if complaint else ""), file=sys.stderr)
        return None
    return out


def split_address(address: str) -> tuple[str, str]:
    """'127.0.0.1:8765' or '[::1]:7679' into the address and the port."""
    host, _, port = address.strip().rpartition(":")
    return host.strip("[]") or "*", port


# ----- the three ways of asking ----------------------------------------

def from_lsof() -> list[dict] | None:
    """Field mode: one letter per line, so nothing is read by column position
    and a program with a space in its name cannot shift everything after it.
    +c 0 turns off the truncation that otherwise cuts a name to nine letters."""
    # lsof exits 1 when it simply matched nothing, which on a machine with no
    # listeners is a true answer rather than a failure.
    # t is the address family, and without it a wildcard listener is reported
    # as *:8080 whether it is IPv4 or IPv6. Two different programs - one on
    # 0.0.0.0:8080, one on [::]:8080 with IPV6_V6ONLY - then looked like one
    # row holding two pids, and the command offered would have ended both.
    output = run(["lsof", "-nP", "+c", "0", "-iTCP", "-sTCP:LISTEN", "-F", "pcLtn"],
                 nothing_found=(1,))
    if output is None:
        return None
    rows, current, family = [], {}, ""
    for line in output.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            current = {"pid": value}
        elif tag == "c":
            current["program"] = value.replace("\\x20", " ")
        elif tag == "L":
            current["user"] = value
        elif tag == "t":
            family = value
        elif tag == "n" and current.get("pid"):
            rows.append({**current, "address": name_family(value, family)})
    return rows


def name_family(address: str, family: str) -> str:
    """A wildcard said in the same words the other tools use.

    lsof writes `*:8080` for both families; netstat and ss write `0.0.0.0:8080`
    and `:::8080`. Saying which one it is keeps two genuinely separate
    listeners apart, and makes the three tools name the same socket the same
    way - which matters because the name is what lines two runs up.
    """
    host, _, port = address.rpartition(":")
    if host == "*":
        return f"{'[::]' if family == 'IPv6' else '0.0.0.0'}:{port}"
    return address


SS_USERS = re.compile(r'\("([^"]+)",pid=(\d+)')


def from_ss() -> list[dict] | None:
    """Linux, where lsof is often not installed. -p needs no privilege to see
    your own processes, and quietly omits other people's."""
    output = run(["ss", "-ltnpH"])
    if output is None:
        return None
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        # Every owner, not the first. A prefork server puts all its workers
        # in one users:(...) field, and ending only the first frees nothing.
        owners = SS_USERS.findall(line)
        if owners:
            rows += [{"pid": pid, "program": program, "user": "",
                      "address": parts[3]} for program, pid in owners]
        else:
            rows.append({"pid": "", "program": "", "user": "", "address": parts[3]})
    # Rows with no pid are kept. Without privilege, ss shows the socket but
    # not whose it is, and dropping those would say the port is free when it
    # is taken - the one wrong answer this table must not give.
    return rows


def netstat_row(parts: list[str]) -> dict | None:
    """One line of netstat, from either of the two programs with that name.

    They share a name and nothing else:

        Windows   TCP  127.0.0.1:8765  0.0.0.0:0  LISTENING  7312
        Linux     tcp  0  0  127.0.0.1:8765  0.0.0.0:*  LISTEN  7312/python3

    Reading the Linux one by the Windows columns found nothing at all and said
    so as an empty table, which reads as "no ports are in use". So the state
    is looked for rather than assumed to be in a particular place, and the
    address is the field before it that has a port on the end.
    """
    if not parts or not parts[0].lower().startswith("tcp"):
        return None

    # The first two fields carrying a port are the local address and the one
    # at the far end, in that order. Taking the last match instead of the
    # first reported every socket as listening on nothing.
    ports = [n for n, part in enumerate(parts) if ":" in part]
    if len(ports) < 2:
        return None
    address, far = parts[ports[0]], parts[ports[1]]

    # A listener is recognised by the far end being nobody - 0.0.0.0:0 and
    # [::]:0 on Windows, 0.0.0.0:* and :::* on Linux - and **not** by the
    # word in the state column. That word is translated: a German Windows
    # says ABHOEREN, and matching only LISTENING made every port on that
    # machine vanish from a table that still reported success.
    if not (far.endswith(":0") or far.endswith(":*")):
        return None

    # Windows puts the pid on its own; Linux -p writes it as 7312/python3,
    # and without privilege writes nothing at all.
    pid, program = "", ""
    for part in parts[ports[1] + 1:]:
        if part.isdigit():
            pid = part
            break
        number, slash, name = part.partition("/")
        if slash and number.isdigit():
            pid, program = number, name
            break
    return {"pid": pid, "address": address, "program": program, "user": ""}


def from_netstat() -> list[dict] | None:
    """Windows, and a Linux with neither lsof nor ss. On Windows tasklist
    supplies the names behind the pids, in CSV - the one format it emits that
    survives a program name with a comma in it."""
    # The two netstats take different flags for the same thing: -o on Windows
    # asks for the owning pid, while -o on Linux asks for timers and the pid
    # comes from -p. Getting that wrong filled every pid, program, kill and
    # command cell with nothing while the table still looked complete.
    #
    # Both are tried rather than chosen by platform name, and the one that
    # came back with owners wins. The wrong one errors or returns no rows.
    answered, sockets = False, ""
    for flags in (["-ano"], ["-lntp"], ["-anp"]):
        output = run(["netstat", *flags])
        if output is None:
            continue
        answered = True
        if any(netstat_row(line.split()) or {} for line in output.splitlines()):
            sockets = output
            if any((netstat_row(line.split()) or {}).get("pid")
                   for line in output.splitlines()):
                break       # it named the owners; nothing better to find
    if not answered:
        return None
    names = {}
    for line in (run(["tasklist", "/fo", "csv", "/nh"]) or "").splitlines():
        parts = next(csv.reader([line]), [])
        if len(parts) >= 2 and parts[1].isdigit():
            names[parts[1]] = parts[0]

    rows = []
    for line in sockets.splitlines():
        row = netstat_row(line.split())
        if row:
            row["program"] = row["program"] or names.get(row["pid"], "")
            rows.append(row)
    return rows


WAYS = (("lsof", from_lsof), ("ss", from_ss), ("netstat", from_netstat))


def pid_then_command(output: str) -> dict[str, str]:
    """Lines of `7312 /usr/bin/python3 -m snapgrid` into pid and command.

    The three tools below are all asked to print in this one shape, so there
    is one thing to parse rather than three. A line with nothing after the
    pid is dropped: it is the same as not having been answered, and keeping
    it would stop a later tool being tried.
    """
    commands = {}
    for line in output.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and command.strip():
            commands[pid] = command.strip()
    return commands


def from_ps(pids: set[str]) -> dict[str, str]:
    """macOS and Linux. An empty pid list would make the argument ",7312",
    which ps rejects outright - losing the command line of every process,
    including the ones that could have been looked up."""
    return pid_then_command(
        run(["ps", "-o", "pid=,command=", "-p", ",".join(sorted(pids))]) or "")


def from_wmic(pids: set[str]) -> dict[str, str]:
    """Windows. `/value` rather than `/format:csv`, because the CSV wmic
    writes does not quote a command line containing a comma - and a command
    line is the one field most likely to hold one.

    `/value` prints `Key=value` lines in alphabetical order, so CommandLine
    arrives before the ProcessId it belongs to. A process whose command line
    cannot be read has no CommandLine line at all, which is why the value is
    cleared after each pid rather than carried into the next.

    wmic is deprecated and is absent from a recent Windows, hence the
    PowerShell way below.
    """
    where = " or ".join(f"ProcessId={pid}" for pid in sorted(pids))
    output = run(["wmic", "process", "where", where,
                  "get", "ProcessId,CommandLine", "/value"]) or ""
    commands, line = {}, ""
    for text in output.splitlines():
        key, equals, value = text.partition("=")
        if not equals:
            continue
        if key.strip() == "CommandLine":
            line = value.strip()
        elif key.strip() == "ProcessId" and value.strip().isdigit():
            commands[value.strip()] = line
            line = ""
    return {pid: line for pid, line in commands.items() if line}


# Everything happens inside cmdlets: no property read, no method call, no
# format operator. A hardened Windows runs PowerShell in constrained language
# mode, where `$_.ProcessId` on a CimInstance is refused outright - the very
# machines this is for are the ones most likely to be in that mode. The
# default table output is no good either, since it truncates a long command
# line with an ellipsis, so it is CSV and the standard library unquotes it.
PS_COMMAND_LINES = ("Get-CimInstance Win32_Process | "
                    "Select-Object ProcessId,CommandLine | "
                    "ConvertTo-Csv -NoTypeInformation")


def from_powershell(pids: set[str]) -> dict[str, str]:
    """Windows without wmic. -NoProfile so a user's profile cannot print
    anything into the answer, -NonInteractive so nothing can ever prompt.

    Every process is asked for and the ones wanted are picked out here: the
    filtering costs a second machine-readable list to build, and a where
    clause of twenty pids written into a command line is a quoting problem
    on the one platform whose quoting cannot be relied on.
    """
    for shell in ("pwsh", "powershell"):
        output = run([shell, "-NoProfile", "-NonInteractive",
                      "-Command", PS_COMMAND_LINES])
        if not output:
            continue
        commands = {}
        for row in csv.reader(output.splitlines()):
            # ProcessId,CommandLine - the order Select-Object was given.
            if len(row) >= 2 and row[0].strip().isdigit() and row[1].strip():
                commands[row[0].strip()] = row[1].strip()
        if commands:
            return {pid: commands[pid] for pid in pids if pid in commands}
    return {}


def full_commands(pids: set[str]) -> dict[str, str]:
    """The whole command line per pid - what tells two copies of `java` apart
    before you end one, and what the program column needs to say anything
    better than "java" in the first place.

    Three ways again, in the order most likely to answer on this machine but
    all of them tried: a Python running under Git Bash reports a Windows
    machine as posix, and asking its ps for a Windows pid answers nothing.

    Allowed to fail entirely: a blank cell beats a failed run, and a process
    that has already gone is the usual reason.
    """
    pids = {pid for pid in pids if pid}
    if not pids:
        # The one exit that used to say nothing at all, which made a silent
        # log mean two different things: nobody to ask about, or asked and
        # told nothing. A day went on telling them apart.
        print("no pids in the table, so there is nothing to look up",
              file=sys.stderr)
        return {}
    print(f"looking up {len(pids)} command lines"
          f" ({os.name}/{sys.platform}, "
          + ", ".join(f"{name}: {'yes' if found(name) else 'no'}"
                      for name in ("wmic", "powershell", "pwsh", "ps")) + ")",
          file=sys.stderr)
    ways = (("wmic", from_wmic), ("powershell", from_powershell), ("ps", from_ps)) \
        if on_windows() else \
        (("ps", from_ps), ("wmic", from_wmic), ("powershell", from_powershell))
    # Each way is named as it is tried, because the failure this has already
    # had once was a silent one: a tool that ran, printed, and was parsed
    # into nothing. "asked wmic, nothing" and "no wmic" are different
    # problems and the log has to tell them apart.
    for name, ask in ways:
        commands = ask(pids)
        if commands:
            print(f"command lines from {name}: {len(commands)} of {len(pids)}",
                  file=sys.stderr)
            return commands
        print(f"{name}: no command lines", file=sys.stderr)
    return {}


# Programs whose own name tells you nothing: what matters is what they were
# told to run. A table of "Python" four times over names nothing at all.
INTERPRETERS = ("python", "python3", "java", "node", "ruby", "perl", "php",
                "sh", "bash", "zsh", "pwsh", "powershell", "deno", "bun")


# Flags that swallow the word after them. Without this the word gets read as
# the thing being run: `java -cp /a/b.jar:/c/d.jar com.acme.Main` would be
# named after the last jar on the class path, which is not even the program -
# a wrong name, which is worse than the useless one it replaced.
TAKES_A_VALUE = {
    "-cp", "-classpath", "--class-path", "-p", "--module-path",
    "--upgrade-module-path", "--add-modules", "--add-opens", "--add-exports",
    "--enable-native-access", "-agentlib", "-agentpath", "-javaagent",
    "-W", "-X", "--require", "-r", "-e",
}
RUNS_WHAT_FOLLOWS = {"-m", "--module", "-jar", "-c", "--eval"}


def base_name(path: str) -> str:
    """The last segment of a path written with either separator.

    os.path.basename knows only the separator of the machine it is running
    on, and these command lines come from Windows while the tests read them
    on a Unix - where `C:\\tools\\jdk\\bin\\java.exe` is one long file name.
    """
    return re.split(r"[\\/]", path)[-1]


def words_of(command: str) -> list[str]:
    """A command line as its words, with a quoted path kept in one piece.

    Windows writes the program as its full path and that path has a space in
    it. `"C:\\Program Files\\Java\\bin\\java.exe" -jar billing.jar` split on
    spaces begins `"C:\\Program`, and `Files\\Java\\bin\\java.exe"` would then
    be read as the thing being run - a wrong name rather than a useless one.
    """
    return [word.replace('"', "")
            for word in re.findall(r'"[^"]*"|\S+', command)]


def running_what(program: str, command: str) -> str:
    """A name worth reading, taken from the command line when the program's
    own name is only the interpreter that happens to be running it.

        python -m snapgrid serve        ->  snapgrid
        python /opt/thing/main.py       ->  main.py
        java -jar billing.jar           ->  billing.jar
        java -cp lib/* com.acme.Billing ->  com.acme.Billing
        node server.js                  ->  server.js

    The class name rather than its last word, because every third Java
    application has a class called Main and knowing which one it is is the
    entire point of the column.

    Only the name is changed; the whole command line is in the next column, so
    nothing is hidden - it is moved to where there is room for it.
    """
    stem = base_name(program).lower().removesuffix(".exe")
    if stem not in INTERPRETERS or not command:
        return program

    words = words_of(command)[1:]       # the interpreter itself is not news
    skip = False
    for index, word in enumerate(words):
        if skip:
            skip = False
            continue
        if word in RUNS_WHAT_FOLLOWS:
            if index + 1 < len(words):
                return base_name(words[index + 1])
            return program
        if word.startswith("-"):
            # -cp /a/b and -Xmx2g are both flags; only the first kind eats
            # the word after it, and =-joined ones carry their own value.
            if word in TAKES_A_VALUE and "=" not in word:
                skip = True
            continue
        name = base_name(word)
        if name and name.lower().removesuffix(".exe") not in INTERPRETERS:
            return name
    return program


def main() -> int:
    rows, asked = None, ""
    for name, ask in WAYS:
        rows = ask()
        if rows is not None:        # it ran; an empty list is its answer
            asked = name
            break

    if rows is None:
        # No way to ask is not the same as nothing to find. Failing keeps the
        # last good table instead of replacing it with emptiness, which would
        # read as "nothing is listening".
        print("could not list listening sockets: none of lsof, ss or netstat "
              "answered. Is one of them on PATH?", file=sys.stderr)
        return 1
    print(f"asked {asked}", file=sys.stderr)

    commands = full_commands({row["pid"] for row in rows})

    # One row per listener, because the listener is what names a row and
    # [table] key has to be unique: two rows called 127.0.0.1:8080 would make
    # the comparison fall back to whole rows, and a cell's history would be
    # read off whichever of them came first.
    #
    # A port genuinely can be held by more than one process - a prefork server
    # whose workers inherit the socket is the usual case - so those are
    # gathered into the one row rather than dropped. The pids go in together
    # and the command ends all of them, which is what you want anyway: killing
    # one worker of four frees nothing.
    by_listener: dict[str, dict] = {}
    for row in sorted(rows, key=lambda one: (int(one["pid"] or 0), one["address"])):
        address, port = split_address(row["address"])
        listener = f"{address}:{port}"
        holder = by_listener.setdefault(listener, {
            "port": port, "pids": [], "users": [], "programs": [], "commands": [],
        })
        if row["pid"] and row["pid"] not in holder["pids"]:
            holder["pids"].append(row["pid"])
            for field, key in (("users", "user"), ("programs", "program")):
                value = row.get(key, "")
                if value and value not in holder[field]:
                    holder[field].append(value)
            command = commands.get(row["pid"], "")
            if command and command not in holder["commands"]:
                holder["commands"].append(command)
            # Worked out after the command line is known, which is why it is
            # not done where the rows are gathered.
            named = running_what(row.get("program", ""), command)
            if named and named not in holder["programs"]:
                holder["programs"] = [named if one == row.get("program") else one
                                      for one in holder["programs"]]

    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(COLUMNS)
    for listener, holder in sorted(by_listener.items(), key=lambda one: int(one[1]["port"])):
        pids = holder["pids"]
        writer.writerow([
            listener, holder["port"], " ".join(pids),
            " ".join(holder["users"]), " ".join(holder["programs"]),
            # No pid, nothing to offer. A command with the number missing
            # would be worse than a blank: it looks runnable.
            kill_command(pids),
            " ".join(holder["commands"]),
        ])

    print(f"{len(by_listener)} listening sockets", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
