# Listening ports

**What has got port 8080, and what do I type to make it let go.**

One row per listening socket, with the pid and a ready-made command to end it.

**What the plugin prints:**

```
listener,port,pid,user,program,kill,command
127.0.0.1:8765,8765,20007,seizner,Python,kill -9 20007,/.../Python -m snapgrid serve --dir ...
*:5000,5000,82822,seizner,ControlCenter,kill -9 82822,/System/Library/CoreServices/ControlCenter.app/...
```

## See it

```bash
./server.py --dir examples
```

It is in the list on the left. To keep it:

```bash
cp -r examples/listening-ports plugins/
```

Then filter the `port` column, or type a port into the search box.

## It refreshes every ten seconds

```toml
[run]
every = "10s"
```

Short, because this is for watching a port change hands: start something and
see it appear, end it and see it go, without touching anything.

It is the shortest interval in any of these examples, and it is not free -
`lsof` walks every open file on the machine each time. Nothing outside this
machine is contacted, so there is nobody to be rude to; but on a laptop running
on its battery, `"1m"` is the kinder setting and loses little.

## It reports; it does not kill

**Nothing is ended by this plugin.** The `kill` column is *text in a cell* -
`kill -9 20007` - for copying into a terminal. You are the one who runs it,
having first read the `command` column and seen what you are about to end.

That split is deliberate and is the rule for every plugin: they read and
report, they do not act. A table that could terminate processes would be a
table you could not safely leave open.

## Why not a shell script

It began as one. `lsof | awk` is a natural fit until the `command` column
arrives: a full command line contains spaces, commas and quotes, and building
CSV by joining strings puts half a path into the next column the first time one
of them turns up. The contract says to use a CSV writer rather than string
concatenation, and in a shell script there is not one.

The second reason is Windows, where there is no `lsof`. In Python both can live
behind one table.

## It runs anywhere, by asking whatever is there

There is no way to ask Python which process holds a socket it does not own, so
this reads the tools the machine already has - **trying three in turn rather
than deciding by the name of the operating system**. `lsof` is missing from
plenty of Linux images; `ss` is not on macOS; `netstat` is what Windows has.
Which one answered is written to the log.

| Tried | Where it is | How it is read |
|---|---|---|
| `lsof -nP +c 0 -iTCP -sTCP:LISTEN -F pcLtn` | macOS, most Linux | field mode: one letter per line (`p` pid, `c` command, `L` user, `n` address) rather than columns, so a program with a space in its name cannot shift everything after it. `+c 0` turns off the truncation that otherwise cuts a name to nine letters. `t` is the address family, without which a wildcard listener reads as `*:8080` whether it is IPv4 or IPv6 - and two separate programs on the two would merge into one row whose kill command ended both |
| `ss -ltnpH` | modern Linux | one line per socket, the pid picked out of `users:(("name",pid=n,...))` |
| `netstat` + `tasklist /fo csv` | Windows, and a Linux with neither of the above | the flags differ: `-o` asks Windows for the owning pid and asks Linux for *timers*, where the owner comes from `-p`. Both forms are tried and the one that named owners wins. A listener is recognised by the far end of the socket being nobody rather than by the word in the state column - that word is translated, and a German Windows says `ABHÖREN`. On Windows `tasklist` supplies the names behind the pids, read as CSV - the one format it emits that survives a program name with a comma in it |

## The command line is asked for separately, and also three ways

None of the three tools above reports it - `lsof` gives the program's name and
nothing more - so it is a second question, asked of whatever can answer.

| Tried | Where it is | How it is read |
|---|---|---|
| `ps -o pid=,command= -p ...` | macOS, Linux | one line per pid |
| `wmic process where "ProcessId=..." get ProcessId,CommandLine /value` | Windows up to 11 23H2 | `Key=value` lines. **Not** `/format:csv`: the CSV wmic writes does not quote a field containing a comma, and a command line is the field most likely to hold one |
| `powershell -NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process \| ..."` | Windows, where wmic has been removed | asked to print `pid command`, the shape `ps` uses, so one parser reads both. `-NoProfile` so a user's profile cannot print into the answer; `-NonInteractive` so nothing can prompt |

All three are tried, in the order most likely to answer first, rather than one
being chosen by the name of the operating system. **A Python under Git Bash
reports a Windows machine as `posix`** - and its `ps` knows nothing about a
Windows pid, so it answers and answers nothing. Falling through to the next way
is what fills the column there.

It is allowed to fail entirely: a blank cell beats a failed run, and a process
that has already gone is the usual reason.

## The kill command is written for this machine

```
kill -9 7312                            macOS, Linux
taskkill /F /PID 7312                   Windows

kill -9 990 991 992                     several processes on one port
taskkill /F /PID 990 /PID 991 /PID 992  the same on Windows
```

`taskkill` needs its own `/PID` before each number; a single flag with three
numbers after it is not a command that ends three processes, it is a command
that fails.

The plugin writes whichever one applies, filled in with the pid. A table of
pids without it is half an answer, and the missing half is different on every
machine - which is exactly what you do not want to be looking up at the moment
you need it.

**A socket whose owner you cannot see gets no command**, and an empty cell
rather than one with the number missing. Without privilege `ss` reports the
socket but not whose it is, and a command that looks runnable and is not would
be worse than nothing. The row stays, because the port is taken either way -
saying it is free would be the one wrong answer this table must not give.

## Text from a console tool

The helpers are read as **bytes and decoded here**, rather than letting Python
decode them with the locale's encoding and refuse what it does not recognise.
A console tool on a localised Windows writes in the OEM code page, which is not
that encoding: on a French install the `É` of `ÉCOUTE` is a byte `cp1252` has
no character for, and the whole run would have ended with a decoding error over
a word this does not even read.

Anything that does not survive becomes a replacement character. Losing an
accent from a program name is nothing; losing the table is not.

## Columns

| Column | Why it is there |
|---|---|
| `listener` | address and port together - what names a row, and unique |
| `port` | the same number on its own, so the column sorts as numbers and filters as a list |
| `pid` | what you need. More than one when several processes share the socket |
| `user` | whose process it is, and therefore whether you can end it |
| `program` | the name worth reading - see below |
| `kill` | the whole command for this machine, ready to copy. Empty when the pid is not visible |
| `command` | the full command line - how you tell two copies of `java` apart before ending one |

`listener` and `port` are the same information twice on purpose. One has to be
text to name a row uniquely; the other has to be a number to sort and filter
usefully.

## "Python" is not a name

A column reading `Python`, `java`, `node`, `java` names nothing. The
interpreter is never what you are looking for; what it was told to run is.

```
python -m snapgrid serve           ->  snapgrid
python /opt/thing/main.py          ->  main.py
java -jar billing.jar              ->  billing.jar
java -cp lib/* com.acme.Billing    ->  com.acme.Billing
node server.js                     ->  server.js
```

**Java is the one that needs care**, because almost nothing is started with
`-jar`. A real service is started with a class path and a main class, and
taking the first word that is not a flag then names it after the last jar on
that path - a wrong name, which is worse than the useless one it replaced. So
the flags that swallow the word after them (`-cp`, `--module-path`,
`-javaagent` and the rest) are known, and skipped with their value.

The **whole** class name is shown, not its last word: every third application
has a class called `Main`, and which one it is is the entire point of the
column. `org.apache.catalina.startup.Bootstrap` says Tomcat; `Bootstrap` says
nothing.

A program whose own name is its name - `nginx`, `Dropbox` - is left alone.
Nothing is hidden either way: the full command line is in the next column.

This works on Windows too, which took a second look. The name there comes from
`tasklist` as `java.exe`, and reading past it needs the command line - which
until the lookup above existed was empty on Windows throughout, so every Java
service read as `java.exe` and every script as `python.exe`.

The other half of it is that **Windows writes the program as its full path, and
that path has a space in it**:

```
"C:\Program Files\Java\jdk-21\bin\java.exe" -cp C:\app\lib\* com.acme.Billing
```

Split on spaces, that command line begins `"C:\Program`, and the word after it
would be read as the thing being run - naming the service `Files\Java\...` -
so a quoted path is kept in one piece. The path separator is read as either
slash, because `os.path.basename` knows only the one belonging to the machine
it is running on.

## A port held by more than one process

A prefork server - nginx, gunicorn, anything whose workers inherit the
listening socket - puts several processes on one port. They are **one row**,
not several: `listener` is what names a row, and snapgrid needs that to be
unique. Two rows called `*:80` would make the comparison give up and fall back
to matching whole rows, and the history of a cell would be read off whichever
of them came first.

So the pids go in together and the command ends all of them:

```
*:80   80   990 991 992   www   nginx   kill -9 990 991 992
```

Which is what you wanted anyway. Killing one worker of four frees nothing: the
others still hold the port, and the parent starts a replacement.

## Nothing is coloured

There is no `[colour]` here, and that is a decision rather than an oversight.
Nothing in this table has a small fixed set of values that means good or bad: a
port is not wrong for being 8080, and colouring every row the same teaches the
eye nothing.

## When it is not working

| What you see | What it means |
|---|---|
| `could not list listening sockets` | none of `lsof`, `ss` or `netstat` is on PATH. The run fails rather than showing an empty table, which would read as "nothing is listening". A tool that *ran* and found nothing is a different thing, and gives a table with no rows |
| fewer rows than you expect | ports held by other users' processes are not all visible to you. Run snapgrid as yourself and expect to see your own |
| an empty `command` | the pid could not be asked about, usually because the process had already gone. Empty for every row means none of `ps`, `wmic` or `powershell` answered - the log says so - and the `program` column then shows the interpreter rather than what it is running |
| an empty `pid` and `kill` | the socket is visible but its owner is not. The port is taken; you cannot see by what without more privilege |
