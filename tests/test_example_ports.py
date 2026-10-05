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
        with mock.patch.object(self.lp.os, "name", "nt"):
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
