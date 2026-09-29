#!/usr/bin/env python3
"""When each TLS certificate expires.

Reads hosts.txt next to it, connects to each one, and reports the expiry date
and how many days are left. No credentials: a server hands its certificate to
anybody who connects, which is the whole point of a public certificate.

The rules for any plugin, in any language:

  * write CSV to standard output, starting with a header line
  * write progress or warnings to standard error, never to standard output
  * exit with code 0 when it worked, anything else when it did not

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

# A handshake either happens quickly or is not going to. Without a timeout an
# unreachable host holds the whole run until [run] timeout kills it, and then
# no other host gets checked either.
TIMEOUT_SECONDS = 6

DEFAULT_PORT = 443


def hosts_to_check() -> list[tuple[str, int]]:
    """Read hosts.txt: one host per line, optionally host:port."""
    source = Path(__file__).with_name("hosts.txt")
    if not source.is_file():
        return []

    found = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()      # allow comments
        if not line:
            continue
        if ":" in line:
            name, _, port = line.rpartition(":")
            found.append((name, int(port) if port.isdigit() else DEFAULT_PORT))
        else:
            found.append((line, DEFAULT_PORT))
    return found


# Some Python installations arrive with no certificate authorities configured
# at all - a python.org build on macOS is the common one - and then every
# handshake fails with "unable to get local issuer certificate", which reads
# like a server problem and is not. The system bundle is usually right there.
SYSTEM_BUNDLES = (
    "/etc/ssl/cert.pem",                        # macOS, BSD
    "/etc/ssl/certs/ca-certificates.crt",       # Debian, Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",         # Red Hat, Fedora
)


def trust_store() -> ssl.SSLContext:
    """A context that verifies, with authorities from wherever they are.

    On Windows the default context reads the Windows certificate store, so a
    corporate authority installed by IT is already trusted and nothing here
    has to happen.
    """
    context = ssl.create_default_context()
    # TLS 1.0 and 1.1 are long broken, and a default context still permits
    # them. Saying so explicitly costs one line, and this is example code that
    # gets copied. A server too old to speak 1.2 will now fail loudly rather
    # than negotiate something nobody should still be using.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if context.get_ca_certs():
        return context

    for candidate in SYSTEM_BUNDLES:
        if Path(candidate).is_file():
            context.load_verify_locations(candidate)
            print(f"using certificate authorities from {candidate}", file=sys.stderr)
            return context

    print("this Python has no certificate authorities configured, so nothing "
          "can be verified", file=sys.stderr)
    return context


def expiry_of(context: ssl.SSLContext, host: str, port: int) -> tuple[datetime, str]:
    """The certificate's expiry and who issued it.

    The certificate is verified. An unverified connection is not a useful
    fallback here: Python only parses a certificate it has checked, so an
    unverified handshake hands back an empty dictionary and there is no date
    in it to report.

    On a network that intercepts TLS, what arrives is the proxy's certificate,
    signed by an authority your machine has been told to trust. It will verify,
    and the date reported is the proxy's. That is not a flaw in this plugin; it
    is what your browser sees too.
    """
    with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secure:
            certificate = secure.getpeercert()

    # notAfter looks like 'Jun  1 12:00:00 2027 GMT' and is always in UTC.
    expires = datetime.strptime(certificate["notAfter"], "%b %d %H:%M:%S %Y %Z")
    expires = expires.replace(tzinfo=timezone.utc)

    issuer = ""
    for part in certificate.get("issuer", ()):
        for key, value in part:
            if key == "organizationName":
                issuer = value
    return expires, issuer


def main() -> int:
    hosts = hosts_to_check()
    if not hosts:
        print("hosts.txt is empty or missing - add one host per line", file=sys.stderr)
        return 1

    context = trust_store()
    print(f"checking {len(hosts)} host(s)", file=sys.stderr)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["host", "expires", "days_left", "issuer"])

    now = datetime.now(timezone.utc)
    reached = 0

    for host, port in hosts:
        try:
            expires, issuer = expiry_of(context, host, port)
        except Exception as exc:
            # One unreachable host must not lose the other twenty. The row is
            # kept with empty values so the host does not vanish from the
            # table, which would read as "this is no longer being watched".
            print(f"{host}: {exc}", file=sys.stderr)
            writer.writerow([host, "", "", ""])
            continue

        # YYYY-MM-DD sorts correctly as text, which is why the contract asks
        # for it rather than a local format.
        writer.writerow([
            host,
            expires.strftime("%Y-%m-%d"),
            (expires - now).days,
            issuer,
        ])
        reached += 1

    if not reached:
        # Every host failed: almost certainly the network, not the servers.
        print("no host could be reached", file=sys.stderr)
        return 1

    print(f"{reached} of {len(hosts)} reached", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
