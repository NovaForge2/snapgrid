# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 NovaForge2
"""The listening-ports example, on output from machines this is not.

The examples have no tests, and mostly need none: they are short, and running
one shows whether it works. This one is different. It reads three different
tools and two of them cannot be run here, so the only way to know the Windows
and Linux branches work is to feed them what those machines actually print.

The samples below are real output, trimmed.
"""

import csv
import importlib.util
import io
import locale
import sys
import unittest
from pathlib import Path
from unittest import mock

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "listening-ports" / "main.py"


def load():
    spec = importlib.util.spec_from_file_location("listening_ports", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1024
  TCP    127.0.0.1:8765         0.0.0.0:0              LISTENING       7312
  TCP    [::]:445               [::]:0                 LISTENING       4
  TCP    127.0.0.1:52001        127.0.0.1:8765         ESTABLISHED     7312
  UDP    0.0.0.0:5353           *:*                                    2100
"""

TASKLIST = ('"svchost.exe","1024","Services","0","12,345 K"\n'
            '"python.exe","7312","Console","1","40,112 K"\n'
            '"My App, Ltd.exe","4","Services","0","1,000 K"\n')

SS = ('LISTEN 0 4096 127.0.0.1:8765 0.0.0.0:* users:(("python3",pid=7312,fd=7))\n'
      'LISTEN 0 511  *:80          *:*      users:(("nginx",pid=990,fd=6))\n'
      'LISTEN 0 128  [::1]:631     [::]:*\n')

LSOF = ("p7312\ncpython3.13\nLseizner\nf7\ntIPv4\nn127.0.0.1:8765\n"
        "p990\ncGoogle\\x20Drive\nLseizner\nf6\ntIPv6\nn[::1]:7679\n"
        "f8\ntIPv4\nn*:5000\n")


class ToolsThatAreNotThere(unittest.TestCase):
    """None and "" are different answers, and the difference decides whether
    the run fails or reports an empty machine."""

    def setUp(self):
        self.lp = load()

    def test_a_missing_tool_gives_nothing_at_all(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(self.lp.run(["lsof"]))
            self.assertIsNone(self.lp.from_lsof())
            self.assertIsNone(self.lp.from_ss())
            self.assertIsNone(self.lp.from_netstat())

    def test_a_tool_that_ran_and_said_nothing_gives_an_empty_list(self):
        with mock.patch.object(self.lp, "run", return_value=""):
            self.assertEqual(self.lp.from_lsof(), [])
            self.assertEqual(self.lp.from_ss(), [])
            self.assertEqual(self.lp.from_netstat(), [])

    def test_bytes_a_decoder_does_not_know_do_not_end_the_run(self):
        # A console tool on a localised Windows writes in the OEM code page.
        # 0x90 is the E of ECOUTE there and is undefined in cp1252, so
        # decoding with the locale's encoding would raise - over a word this
        # does not even read.
        raw = b"  TCP   0.0.0.0:8080   0.0.0.0:0   \x90COUTE   1234\r\n"
        text = self.lp.decode(raw)
        self.assertIn("0.0.0.0:8080", text)
        self.assertEqual(self.lp.netstat_row(text.split()),
                         {"pid": "1234", "address": "0.0.0.0:8080",
                          "program": "", "user": ""})

    def test_decoding_never_raises(self):
        for raw in (b"", b"\xff\xfe\x00", b"ordinary", "already text"):
            self.assertIsInstance(self.lp.decode(raw), str)

    def ran(self, returncode, stdout="", stderr="", **kwargs):
        done = mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
             mock.patch("subprocess.run", return_value=done):
            return self.lp.run(["x"], **kwargs)

    def test_a_failure_is_a_failure_whatever_it_printed(self):
        self.assertIsNone(self.ran(1, stderr="x: no such thing"))
        # Killed by a signal: no output at all, and nothing to report.
        self.assertIsNone(self.ran(-9))
        # Half a table published as a whole one is the worse outcome.
        self.assertIsNone(self.ran(1, stdout="p123\nn127.0.0.1:80\n"))

    def test_matching_nothing_is_not_a_failure_where_that_is_what_it_means(self):
        # lsof exits 1 when it simply matched nothing.
        self.assertEqual(self.ran(1, nothing_found=(1,)), "")
        # ...but not when it also complained.
        self.assertIsNone(self.ran(1, stderr="lsof: no pwd entry",
                                   nothing_found=(1,)))

    def test_a_clean_run_is_its_output(self):
        self.assertEqual(self.ran(0, stdout="p1\n"), "p1\n")

    def test_an_unknown_owner_does_not_cost_the_known_ones_their_commands(self):
        # ",7312" is rejected by ps outright, which emptied every command cell.
        seen = {}
        def remember(command, **_):
            seen["command"] = command
            return "7312 /usr/bin/python3 -m thing\n"
        with mock.patch.object(self.lp, "run", side_effect=remember), \
             mock.patch.object(self.lp.os, "name", "posix"):
            commands = self.lp.full_commands({"", "7312"})
        self.assertNotIn(",7312", " ".join(seen["command"]))
        self.assertEqual(commands.get("7312"), "/usr/bin/python3 -m thing")


class Windows(unittest.TestCase):
    def setUp(self):
        self.lp = load()

    def rows(self):
        def answer(command, **_):
            return TASKLIST if command[0] == "tasklist" else NETSTAT
        with mock.patch.object(self.lp, "run", side_effect=answer):
            return self.lp.from_netstat()

    def test_only_sockets_that_are_listening(self):
        addresses = [row["address"] for row in self.rows()]
        self.assertIn("127.0.0.1:8765", addresses)
        self.assertNotIn("127.0.0.1:52001", addresses, "that one is a connection")

    def test_udp_is_left_out(self):
        self.assertNotIn("0.0.0.0:5353", [row["address"] for row in self.rows()])

    def test_the_name_behind_the_pid_is_found(self):
        by_pid = {row["pid"]: row["program"] for row in self.rows()}
        self.assertEqual(by_pid["7312"], "python.exe")

    def test_a_program_name_with_a_comma_survives(self):
        # tasklist is read as CSV for exactly this: splitting on commas would
        # turn "My App, Ltd.exe" into a name and a stray pid.
        by_pid = {row["pid"]: row["program"] for row in self.rows()}
        self.assertEqual(by_pid["4"], "My App, Ltd.exe")

    def test_an_ipv6_address_is_kept_whole(self):
        self.assertIn("[::]:445", [row["address"] for row in self.rows()])


class NetstatOnEitherKind(unittest.TestCase):
    """Two programs share the name netstat and nothing else.

        Windows   TCP  127.0.0.1:8765  0.0.0.0:0  LISTENING  7312
        Linux     tcp  0  0  127.0.0.1:8765  0.0.0.0:*  LISTEN  7312/python3

    Reading the Linux one by the Windows columns found nothing and reported it
    as an empty table, which reads as "no ports are in use".
    """

    def setUp(self):
        self.lp = load()

    def row(self, line):
        return self.lp.netstat_row(line.split())

    def test_windows(self):
        self.assertEqual(
            self.row("  TCP    127.0.0.1:8765   0.0.0.0:0   LISTENING   7312"),
            {"pid": "7312", "address": "127.0.0.1:8765", "program": "", "user": ""})

    def test_linux_with_the_owner(self):
        self.assertEqual(
            self.row("tcp 0 0 127.0.0.1:8765 0.0.0.0:* LISTEN 7312/python3"),
            {"pid": "7312", "address": "127.0.0.1:8765", "program": "python3", "user": ""})

    def test_linux_without_the_owner(self):
        # No -p, or no privilege: the socket is there and the owner is not.
        self.assertEqual(self.row("tcp 0 0 0.0.0.0:8080 0.0.0.0:* LISTEN off (0.00/0/0)"),
                         {"pid": "", "address": "0.0.0.0:8080", "program": "", "user": ""})

    def test_the_local_address_is_taken_not_the_far_one(self):
        # Taking the last field with a colon instead of the first reported
        # every socket as listening on 0.0.0.0:* - plausible and useless.
        for line in ("  TCP  127.0.0.1:8765 0.0.0.0:0 LISTENING 7312",
                     "tcp 0 0 127.0.0.1:8765 0.0.0.0:* LISTEN 7312/python3"):
            self.assertEqual(self.row(line)["address"], "127.0.0.1:8765", line)

    def test_the_state_word_is_translated_and_is_not_relied_on(self):
        # A German Windows says ABHOEREN, a French one ECOUTE. Matching only
        # LISTENING made every port on those machines vanish from a table that
        # still reported success - the worst shape of wrong answer this has.
        for state in ("LISTENING", "ABH\u00d6REN", "ECOUTE", "\u0421\u041b\u0423\u0428\u0410\u041d\u0418\u0415"):
            row = self.row(f"  TCP   0.0.0.0:8080   0.0.0.0:0   {state}   1234")
            self.assertEqual(row, {"pid": "1234", "address": "0.0.0.0:8080",
                                   "program": "", "user": ""}, state)

    def test_a_connection_is_not_a_listener_in_any_language(self):
        # What makes it a listener is the far end being nobody, so a
        # connection has to stay out however its state is spelt.
        for line in ("  TCP  127.0.0.1:52001  127.0.0.1:8765  HERGESTELLT  7312",
                     "  TCP  127.0.0.1:52002  127.0.0.1:8765  TIME_WAIT",
                     "tcp 0 0 10.0.0.2:52001 10.0.0.9:443 ESTABLISHED 999/curl"):
            self.assertIsNone(self.row(line), line)

    def test_what_is_not_a_listening_tcp_socket(self):
        for line in ("  TCP  127.0.0.1:52001 127.0.0.1:8765 ESTABLISHED 7312",
                     "udp 0 0 0.0.0.0:5353 0.0.0.0:*",
                     "Active Connections",
                     ""):
            self.assertIsNone(self.row(line), line)


class Linux(unittest.TestCase):
    def setUp(self):
        self.lp = load()

    def rows(self):
        with mock.patch.object(self.lp, "run",
                               side_effect=lambda c, **_: SS if c[0] == "ss" else ""):
            return self.lp.from_ss()

    def test_the_pid_and_name_come_out_of_the_users_field(self):
        first = self.rows()[0]
        self.assertEqual((first["pid"], first["program"]), ("7312", "python3"))

    def test_every_process_sharing_a_socket_is_found(self):
        # A prefork server lists all its workers in one users:(...) field.
        # Taking only the first produced a command that frees nothing.
        line = ('LISTEN 0 511 *:80 *:* users:(("nginx",pid=992,fd=6),'
                '("nginx",pid=991,fd=6),("nginx",pid=990,fd=6))\n')
        with mock.patch.object(self.lp, "run",
                               side_effect=lambda c, **_: line if c[0] == "ss" else ""):
            rows = self.lp.from_ss()
        self.assertEqual(sorted(row["pid"] for row in rows), ["990", "991", "992"])

    def test_a_socket_with_no_visible_owner_is_still_a_taken_port(self):
        # Without privilege ss shows the socket but not whose it is. Dropping
        # it would say the port is free when it is not.
        addresses = [row["address"] for row in self.rows()]
        self.assertIn("[::1]:631", addresses)
        owner = [row for row in self.rows() if row["address"] == "[::1]:631"][0]
        self.assertEqual(owner["pid"], "")


class Lsof(unittest.TestCase):
    def setUp(self):
        self.lp = load()

    def rows(self):
        with mock.patch.object(self.lp, "run",
                               side_effect=lambda c, **_: LSOF if c[0] == "lsof" else ""):
            return self.lp.from_lsof()

    def test_one_process_holding_two_ports_gives_two_rows(self):
        addresses = [row["address"] for row in self.rows()]
        # *:5000 is now named by its family, as the other tools name it.
        self.assertEqual(addresses.count("[::1]:7679") + addresses.count("0.0.0.0:5000"), 2)

    def test_a_wildcard_says_which_family_it_is(self):
        # lsof writes *:8080 for both. Two different programs - one on
        # 0.0.0.0:8080, one on [::]:8080 with IPV6_V6ONLY - then became one
        # row holding two pids, and the command offered would have ended
        # both: freeing one port by killing somebody else's service.
        lsof = ("p100\ncone\nLme\nf7\ntIPv4\nn*:8080\n"
                "p200\nctwo\nLme\nf7\ntIPv6\nn*:8080\n")
        with mock.patch.object(self.lp, "run",
                               side_effect=lambda c, **_: lsof if c[0] == "lsof" else ""):
            rows = self.lp.from_lsof()
        self.assertEqual([row["address"] for row in rows], ["0.0.0.0:8080", "[::]:8080"])

    def test_the_two_families_stay_two_rows(self):
        lsof = ("p100\ncone\nLme\nf7\ntIPv4\nn*:8080\n"
                "p200\nctwo\nLme\nf7\ntIPv6\nn*:8080\n")
        out = io.StringIO()
        with mock.patch.object(self.lp, "run",
                               side_effect=lambda c, **_: lsof if c[0] == "lsof" else ""), \
             mock.patch.object(self.lp, "full_commands", lambda pids: {}), \
             mock.patch.object(sys, "stdout", out):
            self.lp.main()
        rows = [row for row in csv.reader(io.StringIO(out.getvalue())) if row][1:]
        self.assertEqual(len(rows), 2, "two listeners, two rows")
        for row in rows:
            self.assertEqual(row[self.lp.COLUMNS.index("pid")].count(" "), 0,
                             "one pid each, not both in one command")

    def test_the_escape_for_a_space_is_undone(self):
        names = {row["program"] for row in self.rows()}
        self.assertIn("Google Drive", names, "lsof writes a space as \\\\x20")


class TheKillCommand(unittest.TestCase):
    """The half of the answer that differs on every machine."""

    def setUp(self):
        self.lp = load()

    def test_unix(self):
        with mock.patch.object(self.lp.os, "name", "posix"):
            self.assertEqual(self.lp.kill_command(["990"]), "kill -9 990")
            self.assertEqual(self.lp.kill_command(["990", "991"]), "kill -9 990 991")

    def test_windows_repeats_the_flag_for_each_process(self):
        # `taskkill /F /PID 990 991` is not a command that ends two
        # processes; it is a command that fails.
        with mock.patch.object(self.lp.os, "name", "nt"), \
             mock.patch.dict(self.lp.os.environ, {}, clear=True):
            self.assertEqual(self.lp.kill_command(["990"]), "taskkill /F /PID 990")
            self.assertEqual(self.lp.kill_command(["990", "991"]),
                             "taskkill /F /PID 990 /PID 991")

    def test_no_pids_means_no_command(self):
        self.assertEqual(self.lp.kill_command([]), "")


class NetstatFlags(unittest.TestCase):
    """-o asks Windows for the owning pid and Linux for timers. Getting that
    wrong left every pid, program and command cell empty while the table still
    looked complete."""

    def setUp(self):
        self.lp = load()

    def test_linux_is_asked_again_with_the_flag_that_names_owners(self):
        def answer(command, **_):
            if command[0] != "netstat":
                return ""
            if command[1] == "-ano":          # runs, but names nobody
                return "tcp 0 0 127.0.0.1:8765 0.0.0.0:* LISTEN off (0.00/0/0)\n"
            return "tcp 0 0 127.0.0.1:8765 0.0.0.0:* LISTEN 7312/python3\n"
        with mock.patch.object(self.lp, "run", side_effect=answer):
            rows = self.lp.from_netstat()
        self.assertEqual(rows, [{"pid": "7312", "address": "127.0.0.1:8765",
                                 "program": "python3", "user": ""}])

    def test_windows_is_satisfied_by_the_first_try(self):
        def answer(command, **_):
            if command[0] == "tasklist":
                return '"python.exe","7312","Console","1","40,112 K"\n'
            if command[1] != "-ano":
                return None                   # not a flag it has
            return "  TCP  127.0.0.1:8765  0.0.0.0:0  LISTENING  7312\n"
        with mock.patch.object(self.lp, "run", side_effect=answer):
            rows = self.lp.from_netstat()
        self.assertEqual(rows, [{"pid": "7312", "address": "127.0.0.1:8765",
                                 "program": "python.exe", "user": ""}])

    def test_no_netstat_at_all_is_still_nothing(self):
        with mock.patch.object(self.lp, "run", return_value=None):
            self.assertIsNone(self.lp.from_netstat())


class NamingWhatIsActuallyRunning(unittest.TestCase):
    """A column of "Python", "java", "node" names nothing.

    The hard one is Java, because almost nothing is started with -jar. A
    service is started with -cp and a class path, and reading the first word
    that is not a flag then names it after the last jar on that path - a wrong
    name, which is worse than the useless one it replaced.
    """

    def setUp(self):
        self.lp = load()

    def name(self, program, command):
        return self.lp.running_what(program, command)

    def test_a_jar(self):
        self.assertEqual(self.name("java", "java -jar /srv/billing.jar --prod"),
                         "billing.jar")

    def test_a_class_path_and_a_main_class(self):
        self.assertEqual(
            self.name("java", "java -Xmx4g -Dfile.encoding=UTF-8 -cp "
                              "/opt/lib/a.jar:/opt/lib/b.jar com.acme.billing.Application "
                              "--server.port=8080"),
            "com.acme.billing.Application")

    def test_the_whole_class_name_not_its_last_word(self):
        # Every third application has a class called Main. Which one it is is
        # the entire point of the column.
        self.assertEqual(self.name("java", "java -classpath /x/y.jar com.acme.Main"),
                         "com.acme.Main")

    def test_an_agent_is_a_flag_not_a_program(self):
        self.assertEqual(
            self.name("java", "java -javaagent:/opt/agent.jar -cp lib/* "
                              "org.apache.catalina.startup.Bootstrap start"),
            "org.apache.catalina.startup.Bootstrap")

    def test_a_module(self):
        for command, expected in (
            ("/usr/bin/Python -m snapgrid serve --dir examples", "snapgrid"),
            ("java --module-path /mods -m com.acme/com.acme.Main", "com.acme.Main"),
        ):
            self.assertEqual(self.name(command.split()[0], command), expected)

    def test_a_script(self):
        for program, command, expected in (
            ("python3", "python3 -W ignore /opt/thing/main.py --port 80", "main.py"),
            ("node", "node --max-old-space-size=4096 /srv/app/server.js", "server.js"),
            ("bash", "/bin/bash /usr/local/bin/start-all.sh", "start-all.sh"),
        ):
            self.assertEqual(self.name(program, command), expected, command)

    def test_a_program_that_is_its_own_name_is_left_alone(self):
        for program, command in (("nginx", "/usr/sbin/nginx -g daemon off;"),
                                 ("Dropbox", "/Applications/Dropbox.app/x/Dropbox")):
            self.assertEqual(self.name(program, command), program)

    def test_nothing_to_go_on_changes_nothing(self):
        self.assertEqual(self.name("python", ""), "python")
        self.assertEqual(self.name("java", "java"), "java")
        self.assertEqual(self.name("java", "java -jar"), "java", "a flag with nothing after it")


class TheTable(unittest.TestCase):
    """What the plugin prints, which is the part snapgrid reads."""

    def setUp(self):
        self.lp = load()

    def printed(self, rows):
        out = io.StringIO()
        with mock.patch.object(self.lp, "WAYS", (("test", lambda: rows),)), \
             mock.patch.object(self.lp, "full_commands", lambda pids: {}), \
             mock.patch.object(sys, "stdout", out):
            code = self.lp.main()
        return code, list(csv.reader(io.StringIO(out.getvalue())))

    def test_every_row_has_the_same_number_of_columns(self):
        code, rows = self.printed([
            {"pid": "7312", "address": "127.0.0.1:8765", "program": "python3", "user": "me"},
            {"pid": "", "address": "[::1]:631", "program": "", "user": ""},
        ])
        self.assertEqual(code, 0)
        self.assertEqual({len(row) for row in rows if row}, {len(self.lp.COLUMNS)})

    def test_the_kill_command_is_the_one_for_this_machine(self):
        # Asserted against the machine running the tests, not against Unix:
        # the suite runs on Windows too, where the right answer is taskkill.
        _, rows = self.printed(
            [{"pid": "7312", "address": "127.0.0.1:8765", "program": "p", "user": ""}])
        self.assertEqual(rows[1][self.lp.COLUMNS.index("kill")],
                         self.lp.kill_command(["7312"]))

    def test_no_pid_means_no_command_rather_than_a_broken_one(self):
        # "kill -9 " with the number missing looks runnable and is not.
        _, rows = self.printed([{"pid": "", "address": "[::1]:631",
                                 "program": "", "user": ""}])
        self.assertEqual(rows[1][self.lp.COLUMNS.index("kill")], "")

    def test_a_program_name_with_a_comma_does_not_shift_the_columns(self):
        _, rows = self.printed([{"pid": "4", "address": "[::]:445",
                                 "program": "My App, Ltd.exe", "user": ""}])
        self.assertEqual(rows[1][self.lp.COLUMNS.index("program")], "My App, Ltd.exe")
        self.assertEqual(len(rows[1]), len(self.lp.COLUMNS))

    def test_the_same_listener_twice_is_one_row(self):
        one = {"pid": "7312", "address": "127.0.0.1:8765", "program": "p", "user": ""}
        _, rows = self.printed([one, dict(one)])
        self.assertEqual(len([row for row in rows if row]), 2, "a header and one row")

    def test_a_listener_shared_by_several_processes_is_one_row(self):
        # A prefork server's workers inherit the socket. [table] key has to be
        # unique, or the comparison falls back to whole rows and a cell's
        # history is read off whichever row came first.
        workers = [{"pid": str(pid), "address": "*:80", "program": "nginx", "user": "www"}
                   for pid in (990, 991, 992)]
        _, rows = self.printed(workers)
        self.assertEqual(len([row for row in rows if row]), 2, "a header and one row")
        row = rows[1]
        self.assertEqual(row[self.lp.COLUMNS.index("pid")], "990 991 992")
        self.assertEqual(row[self.lp.COLUMNS.index("program")], "nginx",
                         "the same name three times is said once")

    def test_the_command_ends_every_process_holding_the_port(self):
        # Killing one worker of four frees nothing.
        workers = [{"pid": str(pid), "address": "*:80", "program": "nginx", "user": ""}
                   for pid in (990, 991)]
        _, rows = self.printed(workers)
        self.assertEqual(rows[1][self.lp.COLUMNS.index("kill")],
                         self.lp.kill_command(["990", "991"]))
        self.assertIn("991", rows[1][self.lp.COLUMNS.index("kill")])

    def test_every_listener_appears_once(self):
        rows_in = [
            {"pid": "1", "address": "*:80", "program": "a", "user": ""},
            {"pid": "2", "address": "*:80", "program": "b", "user": ""},
            {"pid": "3", "address": "*:443", "program": "c", "user": ""},
        ]
        _, rows = self.printed(rows_in)
        listeners = [row[0] for row in rows[1:] if row]
        self.assertEqual(len(listeners), len(set(listeners)))

    def test_a_machine_with_no_listeners_prints_a_header_and_succeeds(self):
        # A tool that ran and found nothing has answered the question. Only a
        # tool that could not run leaves it unanswered.
        out = io.StringIO()
        with mock.patch.object(self.lp, "WAYS", (("test", lambda: []),)), \
             mock.patch.object(sys, "stdout", out):
            self.assertEqual(self.lp.main(), 0)
        self.assertEqual(out.getvalue().strip(), ",".join(self.lp.COLUMNS))

    def test_nothing_to_ask_fails_rather_than_printing_an_empty_table(self):
        # An empty table reads as "nothing is listening", which is a different
        # and wrong answer. Failing leaves the last good result on screen.
        out = io.StringIO()
        with mock.patch.object(self.lp, "WAYS", (("test", lambda: None),)), \
             mock.patch.object(sys, "stdout", out):
            self.assertEqual(self.lp.main(), 1)
        self.assertEqual(out.getvalue(), "")

    def test_the_port_is_split_off_whatever_the_address_looks_like(self):
        for address, expected in (("127.0.0.1:8765", ("127.0.0.1", "8765")),
                                  ("[::1]:631", ("::1", "631")),
                                  ("*:5000", ("*", "5000")),
                                  (":::445", ("::", "445"))):
            self.assertEqual(self.lp.split_address(address), expected, address)


WMIC = (
    "\r\n\r\nCommandLine=\"C:\\Program Files\\Java\\jdk-21\\bin\\java.exe\" "
    "-Xmx2g -cp C:\\app\\lib\\* com.acme.Billing --port 8080\r\n"
    "ProcessId=7312\r\n\r\n\r\n"
    "ProcessId=4\r\n\r\n\r\n"                       # a System process: no command line
    "CommandLine=C:\\Windows\\system32\\svchost.exe -k RPCSS\r\n"
    "ProcessId=1024\r\n\r\n"
)

# CSV, because a locked-down Windows refuses the format operator and the
# property reads the older shape needed. See PowerShellOnALockedDownMachine.
POWERSHELL = (
    '"ProcessId","CommandLine"\r\n'
    '"7312","""C:\\Program Files\\Java\\jdk-21\\bin\\java.exe"" -jar billing.jar"\r\n'
    '"1024","C:\\Windows\\system32\\svchost.exe -k RPCSS"\r\n'
    '"9999","C:\\Windows\\explorer.exe"\r\n'
)


class TheCommandLineOnWindows(unittest.TestCase):
    """The column was empty on Windows throughout, and that emptiness also
    left the program column saying `java.exe` - there was nothing to read the
    real name out of."""

    def setUp(self):
        self.lp = load()

    def test_wmic_is_read_as_key_equals_value(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: WMIC):
            found = self.lp.from_wmic({"7312", "1024", "4"})
        self.assertEqual(found["1024"], "C:\\Windows\\system32\\svchost.exe -k RPCSS")
        self.assertIn("com.acme.Billing", found["7312"])

    def test_a_comma_in_a_command_line_survives(self):
        # The reason for /value rather than /format:csv: the CSV wmic writes
        # does not quote a field containing a comma.
        output = ("CommandLine=C:\\app\\run.exe --tags one,two,three\r\n"
                  "ProcessId=55\r\n")
        with mock.patch.object(self.lp, "run", lambda *a, **k: output):
            found = self.lp.from_wmic({"55"})
        self.assertEqual(found["55"], "C:\\app\\run.exe --tags one,two,three")

    def test_a_process_with_no_command_line_does_not_borrow_the_last_one(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: WMIC):
            found = self.lp.from_wmic({"7312", "1024", "4"})
        self.assertNotIn("4", found, "pid 4 has no command line of its own")

    def test_powershell_answers_only_about_the_pids_asked_for(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: POWERSHELL):
            found = self.lp.from_powershell({"7312", "1024"})
        self.assertEqual(set(found), {"7312", "1024"})

    def test_powershell_is_asked_without_a_profile_or_a_prompt(self):
        asked = []
        def answer(command, **_):
            asked.append(command)
            return POWERSHELL
        with mock.patch.object(self.lp, "run", side_effect=answer):
            self.lp.from_powershell({"7312"})
        self.assertIn("-NoProfile", asked[0])
        self.assertIn("-NonInteractive", asked[0])

    def test_windows_asks_wmic_before_ps(self):
        asked = []
        def answer(command, **_):
            asked.append(command[0])
            return WMIC if command[0] == "wmic" else ""
        with mock.patch.object(self.lp, "run", side_effect=answer), \
             mock.patch.object(self.lp.os, "name", "nt"):
            found = self.lp.full_commands({"7312"})
        self.assertEqual(asked, ["wmic"], "nothing else needed asking")
        self.assertIn("com.acme.Billing", found["7312"])

    def test_a_posix_python_on_a_windows_machine_still_gets_there(self):
        # Git Bash: os.name is posix, ps exists and knows nothing about a
        # Windows pid. Falling through rather than stopping at the first way
        # is what fills the column there.
        def answer(command, **_):
            return WMIC if command[0] == "wmic" else ""
        with mock.patch.object(self.lp, "run", side_effect=answer), \
             mock.patch.object(self.lp.os, "name", "posix"), \
             mock.patch.object(self.lp.sys, "platform", "linux"):
            found = self.lp.full_commands({"7312"})
        self.assertIn("com.acme.Billing", found["7312"])

    def test_nothing_answering_is_an_empty_cell_not_a_failure(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: None):
            self.assertEqual(self.lp.full_commands({"7312"}), {})

    def test_msys_counts_as_windows_for_the_kill_command(self):
        # taskkill rather than kill, because the pids are Windows pids - and
        # with the doubled slash, because the shell that calls itself msys is
        # the shell that rewrites a single one into a path. This test used to
        # assert the single slash, which is the bug it was meant to guard.
        with mock.patch.object(self.lp.os, "name", "posix"), \
             mock.patch.object(self.lp.sys, "platform", "msys"):
            self.assertTrue(self.lp.on_windows())
            self.assertEqual(self.lp.kill_command(["990"]), "taskkill //F //PID 990")


class AWindowsCommandLine(unittest.TestCase):
    """Written with the program's full path, and that path has a space in it."""

    def setUp(self):
        self.lp = load()

    def test_a_quoted_path_stays_one_word(self):
        words = self.lp.words_of('"C:\\Program Files\\Java\\bin\\java.exe" -jar b.jar')
        self.assertEqual(words, ["C:\\Program Files\\Java\\bin\\java.exe", "-jar", "b.jar"])

    def test_the_class_name_is_found_past_the_class_path(self):
        name = self.lp.running_what(
            "java.exe",
            '"C:\\Program Files\\Java\\jdk-21\\bin\\java.exe" -Xmx2g '
            '-cp C:\\app\\lib\\* com.acme.Billing --port 8080')
        self.assertEqual(name, "com.acme.Billing")

    def test_the_script_is_found_behind_a_windows_python(self):
        name = self.lp.running_what(
            "python.exe",
            'C:\\Python313\\python.exe C:\\tools\\report\\main.py --once')
        self.assertEqual(name, "main.py")

    def test_a_jar_is_found_behind_a_quoted_java(self):
        name = self.lp.running_what(
            "java.exe",
            '"C:\\Program Files\\Java\\bin\\java.exe" -jar C:\\app\\billing.jar')
        self.assertEqual(name, "billing.jar")

    def test_a_program_that_is_its_own_name_is_left_alone(self):
        self.assertEqual(
            self.lp.running_what("nginx.exe", "C:\\nginx\\nginx.exe -g daemon off;"),
            "nginx.exe")

    def test_a_windows_program_is_found_with_its_extension(self):
        # Git Bash: shutil.which adds the .exe only when Python thinks it is
        # on Windows, and an MSYS Python does not.
        def which(program):
            return "C:\\Windows\\system32\\wmic.exe" if program.endswith(".exe") else None
        with mock.patch("shutil.which", side_effect=which), \
             mock.patch.object(self.lp.os, "name", "posix"), \
             mock.patch.object(self.lp.sys, "platform", "msys"):
            self.assertIsNotNone(self.lp.found("wmic"))
        with mock.patch("shutil.which", side_effect=which), \
             mock.patch.object(self.lp.sys, "platform", "linux"), \
             mock.patch.object(self.lp.os, "name", "posix"):
            self.assertIsNone(self.lp.found("wmic"), "no .exe guessing on a Unix")

    def test_the_program_is_started_by_the_path_it_was_found_at(self):
        started = {}
        done = mock.Mock(returncode=0, stdout="out", stderr="")
        def record(command, **_):
            started["argv"] = command
            return done
        with mock.patch("shutil.which", return_value="C:\\Windows\\wmic.exe"), \
             mock.patch("subprocess.run", side_effect=record):
            self.lp.run(["wmic", "process"])
        self.assertEqual(started["argv"], ["C:\\Windows\\wmic.exe", "process"])


class WmicWritesTwoByteText(unittest.TestCase):
    """The failure that cost a second day. wmic writes UTF-16 when its output
    is a pipe, and this is always a pipe. A single byte code page accepts
    every one of those bytes without raising, so nothing is logged, nothing
    throws, and the parser simply never matches - an empty column on a run
    that reports success."""

    def setUp(self):
        self.lp = load()

    PLAIN = "CommandLine=C:\\app\\run.exe --once\r\nProcessId=55\r\n"

    def test_a_byte_order_mark_is_believed(self):
        for encoding, bom in (("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            raw = bom + self.PLAIN.encode(encoding)
            self.assertEqual(self.lp.decode(raw).replace("\r\n", "\n"),
                             self.PLAIN.replace("\r\n", "\n"), encoding)

    def test_two_byte_text_without_a_mark_is_recognised_anyway(self):
        raw = self.PLAIN.encode("utf-16-le")
        self.assertNotIn("\x00", self.lp.decode(raw))
        self.assertIn("CommandLine=C:\\app\\run.exe --once", self.lp.decode(raw))

    def test_wmic_in_utf16_is_parsed(self):
        raw = b"\xff\xfe" + self.PLAIN.encode("utf-16-le")
        with mock.patch.object(self.lp, "run", lambda *a, **k: self.lp.decode(raw)):
            found = self.lp.from_wmic({"55"})
        self.assertEqual(found, {"55": "C:\\app\\run.exe --once"})

    def test_ordinary_single_byte_text_is_left_alone(self):
        for text in ("plain ascii\r\n", ""):
            self.assertEqual(self.lp.decode(text.encode("utf-8")), text, repr(text))

    def test_an_accent_survives_whatever_this_machine_writes_in(self):
        # In the machine's own encoding, not in UTF-8. A console tool writes
        # in the local code page, and asserting UTF-8 here asserted that the
        # machine running the tests is a Mac: on Windows the same bytes come
        # back as two replacement characters, which is what CI said the first
        # time it was ever asked.
        text = "\u00e9\u00e8 accents\n"
        encoding = locale.getpreferredencoding(False)
        try:
            raw = text.encode(encoding)
        except UnicodeEncodeError:
            self.skipTest(f"{encoding} cannot write an accent")
        self.assertEqual(self.lp.decode(raw), text)

    def test_one_stray_zero_does_not_make_it_two_byte_text(self):
        raw = b"  TCP   0.0.0.0:8080   0.0.0.0:0   LISTENING   1234\x00\r\n"
        self.assertIn("0.0.0.0:8080", self.lp.decode(raw))


class PowerShellOnALockedDownMachine(unittest.TestCase):
    """Constrained language mode refuses `$_.ProcessId` on a CimInstance, and
    the machines this plugin exists for are the ones most likely to be in it.
    Everything is done inside cmdlets instead, and comes back as CSV."""

    def setUp(self):
        self.lp = load()

    CSV = ('"ProcessId","CommandLine"\r\n'
           '"7312","""C:\\Program Files\\Java\\bin\\java.exe"" -jar billing.jar"\r\n'
           '"1024","C:\\Windows\\run.exe --tags one,two"\r\n'
           '"4",""\r\n')

    def test_the_command_asks_for_nothing_a_locked_shell_refuses(self):
        asked = self.lp.PS_COMMAND_LINES
        for refused in ("$_.", "-f ", "ForEach-Object", ".Invoke("):
            self.assertNotIn(refused, asked, f"{refused!r} is refused in constrained mode")
        self.assertIn("Select-Object", asked)

    def test_csv_is_unquoted_by_the_standard_library(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: self.CSV):
            found = self.lp.from_powershell({"7312", "1024"})
        self.assertEqual(found["7312"],
                         '"C:\\Program Files\\Java\\bin\\java.exe" -jar billing.jar')
        self.assertEqual(found["1024"], "C:\\Windows\\run.exe --tags one,two")

    def test_a_process_with_no_command_line_is_not_an_answer(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: self.CSV):
            self.assertNotIn("4", self.lp.from_powershell({"4", "1024"}))


class TheLogSaysWhichWayAnswered(unittest.TestCase):
    """"asked wmic, got nothing" and "there is no wmic" are different
    problems with the same empty column, and only the log can tell them
    apart. Guessing between them took a day."""

    def setUp(self):
        self.lp = load()

    def said(self, answer):
        noise = io.StringIO()
        with mock.patch.object(self.lp, "run", lambda *a, **k: answer), \
             mock.patch.object(self.lp.os, "name", "nt"), \
             mock.patch.object(sys, "stderr", noise):
            self.lp.full_commands({"7312"})
        return noise.getvalue()

    def test_every_way_that_came_back_empty_is_named(self):
        said = self.said(None)
        for name in ("wmic", "powershell", "ps"):
            self.assertIn(f"{name}: no command lines", said)

    def test_the_way_that_answered_is_named_with_a_count(self):
        said = self.said("CommandLine=C:\\app\\run.exe\r\nProcessId=7312\r\n")
        self.assertIn("command lines from wmic: 1 of 1", said)


class NoExitIsSilent(unittest.TestCase):
    """A log saying nothing meant two opposite things - nobody to ask about,
    or asked and told nothing - and a day went on telling them apart from a
    distance."""

    def setUp(self):
        self.lp = load()

    def test_a_table_with_no_pids_says_so(self):
        noise = io.StringIO()
        with mock.patch.object(sys, "stderr", noise):
            self.assertEqual(self.lp.full_commands({"", ""}), {})
        self.assertIn("no pids", noise.getvalue())

    def test_the_machine_and_the_tools_on_it_are_written_down(self):
        noise = io.StringIO()
        with mock.patch.object(self.lp, "run", lambda *a, **k: None), \
             mock.patch.object(sys, "stderr", noise):
            self.lp.full_commands({"7312"})
        said = noise.getvalue()
        self.assertIn("looking up 1 command lines", said)
        for name in ("wmic", "powershell", "pwsh", "ps"):
            self.assertIn(name + ":", said)


class WmicExactlyAsItArrives(unittest.TestCase):
    """Not a tidied-up sample: UTF-16LE with a byte order mark, and `\r\r\n`
    between lines, which is what /value really emits. Every earlier fixture
    here was written by hand and agreed with the parser by construction -
    which is how two days went by with the column still empty."""

    REAL = ("\r\r\n"
            "CommandLine=\"C:\\Program Files\\Java\\bin\\java.exe\" -jar billing.jar\r\r\n"
            "ProcessId=7312\r\r\n"
            "\r\r\n"
            "ProcessId=4\r\r\n"           # System: no command line to read
            "\r\r\n")

    def setUp(self):
        self.lp = load()
        self.raw = b"\xff\xfe" + self.REAL.encode("utf-16-le")

    def test_it_decodes_to_something_with_no_zeroes_in_it(self):
        self.assertNotIn("\x00", self.lp.decode(self.raw))

    def test_the_whole_chain_ends_at_a_name_worth_reading(self):
        with mock.patch.object(self.lp, "run", lambda *a, **k: self.lp.decode(self.raw)):
            found = self.lp.from_wmic({"7312", "4"})
        self.assertEqual(found["7312"],
                         '"C:\\Program Files\\Java\\bin\\java.exe" -jar billing.jar')
        self.assertNotIn("4", found)
        self.assertEqual(self.lp.running_what("java.exe", found["7312"]), "billing.jar")



class TheShellDecidesTheSlash(unittest.TestCase):
    """The kill command was written for the operating system when what
    decides its spelling is the shell it will be pasted into. Git Bash
    rewrites an argument that looks like an absolute path, so `taskkill /F`
    reaches taskkill as `taskkill C:/Program Files/Git/F` and fails - on the
    one kind of machine this plugin is for."""

    def setUp(self):
        self.lp = load()

    def windows(self, environment):
        return mock.patch.object(self.lp.os, "name", "nt"), \
               mock.patch.dict(self.lp.os.environ, environment, clear=True)

    def test_git_bash_gets_the_doubled_slash(self):
        name, env = self.windows({"MSYSTEM": "MINGW64"})
        with name, env:
            self.assertTrue(self.lp.in_a_posix_shell())
            self.assertEqual(self.lp.kill_command(["990"]), "taskkill //F //PID 990")
            self.assertEqual(self.lp.kill_command(["990", "991"]),
                             "taskkill //F //PID 990 //PID 991")

    def test_cmd_gets_the_single_slash(self):
        name, env = self.windows({})
        with name, env:
            self.assertFalse(self.lp.in_a_posix_shell())
            self.assertEqual(self.lp.kill_command(["990"]), "taskkill /F /PID 990")

    def test_a_cygwin_python_counts_even_with_no_msystem(self):
        name, env = self.windows({})
        with name, env, mock.patch.object(self.lp.sys, "platform", "cygwin"):
            self.assertEqual(self.lp.kill_command(["990"]), "taskkill //F //PID 990")

    def test_a_unix_is_untouched_by_any_of_this(self):
        with mock.patch.object(self.lp.os, "name", "posix"), \
             mock.patch.object(self.lp.sys, "platform", "linux"), \
             mock.patch.dict(self.lp.os.environ, {"MSYSTEM": "MINGW64"}, clear=True):
            self.assertEqual(self.lp.kill_command(["990"]), "kill -9 990")

    def test_the_log_says_which_spelling_it_chose(self):
        noise = io.StringIO()
        name, env = self.windows({"MSYSTEM": "MINGW64"})
        with name, env, \
             mock.patch.object(self.lp, "WAYS", (("test", lambda: []),)), \
             mock.patch.object(self.lp, "full_commands", lambda pids: {}), \
             mock.patch.object(sys, "stdout", io.StringIO()), \
             mock.patch.object(sys, "stderr", noise):
            self.lp.main()
        self.assertIn("taskkill //F //PID", noise.getvalue())
        self.assertIn("MINGW64", noise.getvalue())
