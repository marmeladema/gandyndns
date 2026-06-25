# Gandyndns

[![CI](https://github.com/marmeladema/gandyndns/actions/workflows/ci.yml/badge.svg)](https://github.com/marmeladema/gandyndns/actions/workflows/ci.yml)

## What is Gandyndns?
Gandyndns is a dynamic IP updater based on the Gandi LiveDNS API.
It can handle both IPv4 and IPv6, although care should be taken for IPv6 if you
use dynamic/temporary addresses.

## How does it work?
Well, read the code, it's pretty simple :]

It first retrieves the machine's current public address(es) from
[ipify](https://www.ipify.org) (IPv4 via `api.ipify.org`, IPv6 via
`api6.ipify.org`). Then, for each record type of each record of each domain in
the configuration, it:

1. retrieves the current record from Gandi;
2. leaves it untouched if it already matches the current address;
3. otherwise updates Gandi with the current address.

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
