# Gandyndns

[![CI](https://github.com/marmeladema/gandyndns/actions/workflows/ci.yml/badge.svg)](https://github.com/marmeladema/gandyndns/actions/workflows/ci.yml)

## What is Gandyndns?
Gandyndns is a dynamic IP updater based on the Gandi LiveDNS API.
It handles both IPv4 and IPv6. For IPv6 it advertises the host's stable,
internet-routable address rather than a short-lived temporary one (see
[IPv6 addressing](#ipv6-addressing)).

## How does it work?
Well, read the code, it's pretty simple :]

It first determines the machine's current public address(es):

- IPv4 (`{remote_addr}`) from [ipify](https://www.ipify.org) (`api.ipify.org`);
- IPv6 (`{remote_addr6}`) from the host's own network interfaces, picking the
  canonical stable global address (see [IPv6 addressing](#ipv6-addressing)).

Then, for each record type of each record of each domain in the configuration, it:

1. retrieves the current record from Gandi;
2. leaves it untouched if it already matches the current address;
3. otherwise updates Gandi with the current address.

A record whose value needs an address that could not be determined is skipped
with a warning rather than failing the run.

It runs once and exits, so it is meant to be triggered periodically (see
[Running it periodically](#running-it-periodically)).

## How to install it?
    python3 -m pip install .

If you do not plan to share it among different users, you can (and maybe should) install it in your own user site-package directory with:

    python3 -m pip install --user .

You can also install it in a virtualenv.

## How to use it?

Configuration file is written in json format.

### Getting credentials
Gandyndns authenticates against the Gandi LiveDNS API with either a Personal
Access Token (PAT, recommended) or a legacy API key. You can create either from
your Gandi account under *Security*. The credential only needs permission to
manage the DNS records of the relevant domain(s).

In the configuration, use `"token"` for a PAT or `"apikey"` for a legacy API
key. If both are present, the token takes precedence:

    "token": "your-personal-access-token"
    "apikey": "your-legacy-api-key"

### Basic configuration
    {
        "domains": {
            "example.com": {
                "apikey": "d41d8cd98f00b204e9800998ecf8427e",
                "records": {
                    "test": {
                        "A": {
                            "rrset_values": ["{remote_addr}"]
                        }
                    }
                }
            }
        }
    }

The `{remote_addr}` placeholder is replaced with the current public IPv4
address. For IPv6, use `{remote_addr6}` together with an `AAAA` record. You can
mix both, and define several records per domain:

    {
        "domains": {
            "example.com": {
                "apikey": "d41d8cd98f00b204e9800998ecf8427e",
                "records": {
                    "test": {
                        "A": {
                            "rrset_values": ["{remote_addr}"]
                        },
                        "AAAA": {
                            "rrset_values": ["{remote_addr6}"]
                        }
                    }
                }
            }
        }
    }

You can either have different config files or have multiple domains in the same config file, as you wish.

### IPv6 addressing
Unlike IPv4, IPv6 hosts typically own a globally routable address directly, and
many use [RFC 4941](https://www.rfc-editor.org/rfc/rfc4941) *temporary/privacy*
addresses for outbound traffic. Asking an external service such as ipify would
therefore report a short-lived temporary address — the wrong thing to publish in
a DNS record. Instead, gandyndns reads the host's own interfaces (Linux
`/proc/net/if_inet6`) and selects the **stable, global, non-temporary** address.

By default the chosen address is then verified against ipify on a best-effort
basis: the request is bound to that source address and, if ipify confirms it,
it is used. If ipify disagrees, the next candidate is tried; if ipify is
unreachable, the local address is used anyway so an outage does not block
updates. When no stable global IPv6 address can be determined (a non-Linux host,
no `/proc/net/if_inet6`, or only temporary addresses present), the `AAAA` record
is skipped with a warning.

Two optional top-level configuration keys tune this behaviour:

    {
        "interface": "eth0",
        "verify_ipv6": true,
        "domains": { ... }
    }

- `interface`: restrict IPv6 discovery to a single interface (useful with
  multiple NICs, VPNs or container bridges). Defaults to all interfaces.
- `verify_ipv6`: set to `false` to skip the ipify cross-check and trust the
  locally discovered address directly. Defaults to `true`.

### Basic usage
    $ gandyndns /path/to/gandyndns.json

or, equivalently:

    $ gandyndns -c /path/to/gandyndns.json
    $ python3 -m gandyndns /path/to/gandyndns.json

If no path is given, gandyndns looks for `gandyndns.json` in the standard
per-user and system configuration directories (as resolved by
[platformdirs](https://pypi.org/project/platformdirs/); on Linux this is
typically `~/.config/gandyndns/gandyndns.json` and `/etc/gandyndns/gandyndns.json`).

Logging can be tuned with `--logging-level` (a numeric level, default `20` =
`INFO`) and `--logging-handler` (`stdout`, `file:/path/to/log` or `syslog`).

Gandyndns does not need any privilege besides internet access to run, so avoid running it as root.

### Running it periodically
Gandyndns updates your records once and exits, so schedule it to run regularly.
With cron, updating every 15 minutes:

    */15 * * * * gandyndns /path/to/gandyndns.json

Or with a systemd timer, pair a `gandyndns.service` (`Type=oneshot`) with a
`gandyndns.timer` using `OnUnitActiveSec=15min`.

## Development

Install the package together with its test dependencies and run the suite:

    python3 -m pip install -e '.[test]'
    python3 -m pytest

Cheers
