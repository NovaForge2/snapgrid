#!/usr/bin/env python3
"""Whether each endpoint answers, and how quickly.

Reads urls.txt next to it, asks each URL for its headers, and reports the
status code and how long it took.

The rules for any plugin, in any language:

  * write CSV to standard output, starting with a header line
  * write progress or warnings to standard error, never to standard output
  * exit with code 0 when it worked, anything else when it did not

Run it by hand to see exactly what snapgrid sees:

    python3 main.py
"""

import csv
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

TIMEOUT_SECONDS = 8

# A plugin reports; it does not act. HEAD asks for the headers and no body,
# which is the lightest question that still proves the thing is answering, and
# cannot change anything at the other end.
METHOD = "HEAD"


# Some Python installations arrive with no certificate authorities configured
# - a python.org build on macOS is the common one - and then every https call
# fails with "unable to get local issuer certificate", which reads like the
# endpoint is broken and is not. On Windows the default context reads the
# Windows store, so a corporate authority is already trusted.
SYSTEM_BUNDLES = (
    "/etc/ssl/cert.pem",                        # macOS, BSD
    "/etc/ssl/certs/ca-certificates.crt",       # Debian, Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",         # Red Hat, Fedora
)


def trust_store() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if context.get_ca_certs():
        return context
    for candidate in SYSTEM_BUNDLES:
        if Path(candidate).is_file():
            context.load_verify_locations(candidate)
            print(f"using certificate authorities from {candidate}", file=sys.stderr)
            return context
    print("this Python has no certificate authorities configured; https will fail",
          file=sys.stderr)
    return context


def urls_to_check() -> list[str]:
    source = Path(__file__).with_name("urls.txt")
    if not source.is_file():
        return []
    found = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            found.append(line)
    return found


def check(context: ssl.SSLContext, url: str) -> tuple[str, str]:
    """The status and the milliseconds it took.

    A 404 or a 500 is an answer, not an error: the endpoint is up and saying
    something, and that belongs in the table rather than in the log. Only a
    connection that never completes has no status to report.
    """
    request = urllib.request.Request(url, method=METHOD)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS,
                                    context=context) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code                     # it answered, just not with a 200
    elapsed = (time.monotonic() - started) * 1000
    return str(status), str(round(elapsed))


def main() -> int:
    urls = urls_to_check()
    if not urls:
        print("urls.txt is empty or missing - add one URL per line", file=sys.stderr)
        return 1

    context = trust_store()
    print(f"checking {len(urls)} endpoint(s)", file=sys.stderr)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["endpoint", "host", "status", "ms"])

    answered = 0
    for url in urls:
        host = urlparse(url).netloc
        try:
            status, milliseconds = check(context, url)
        except Exception as exc:
            # Nothing answered at all: no status, no timing. The row stays so
            # the endpoint does not quietly vanish from the table.
            print(f"{url}: {exc}", file=sys.stderr)
            writer.writerow([url, host, "", ""])
            continue

        writer.writerow([url, host, status, milliseconds])
        answered += 1

    if not answered:
        print("nothing answered - check the network before the endpoints",
              file=sys.stderr)
        return 1

    print(f"{answered} of {len(urls)} answered", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
