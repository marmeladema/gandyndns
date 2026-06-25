"""Core logic for gandyndns.

Update Gandi LiveDNS records so that they match the machine's current
public IP address(es).
"""

from __future__ import annotations

import ipaddress
import logging
import string
import sys
from copy import deepcopy
from typing import List, Mapping, Optional

import requests

# Base URL of the Gandi LiveDNS REST API.
GANDI_API_URL = "https://api.gandi.net/v5/livedns"

# Services used to discover the machine's current public IP addresses,
# keyed by the placeholder name that can be used in record values.
IPIFY_URLS = {
	"remote_addr": "https://api.ipify.org/?format=json",
	"remote_addr6": "https://api6.ipify.org/?format=json",
}

# Default timeout (seconds) for outbound HTTP requests so that an unreachable
# endpoint cannot hang a run indefinitely.
HTTP_TIMEOUT = 10

# Linux exposes per-interface IPv6 addresses, with their scope and flags, here.
PROC_NET_IF_INET6 = "/proc/net/if_inet6"

# Address scope value for global addresses in /proc/net/if_inet6.
IPV6_SCOPE_GLOBAL = 0x00

# Lower-byte IFA_F_* address flags as exposed by /proc/net/if_inet6.
IFA_F_TEMPORARY = 0x01
IFA_F_DADFAILED = 0x08
IFA_F_DEPRECATED = 0x20
IFA_F_TENTATIVE = 0x40
IFA_F_PERMANENT = 0x80

# Flags that disqualify an address from being advertised outright.
_IFA_F_UNUSABLE = IFA_F_TEMPORARY | IFA_F_TENTATIVE | IFA_F_DADFAILED

_module_logger = logging.getLogger("gandyndns")


def _ensure_logger(logger: Optional[logging.Logger]) -> logging.Logger:
	"""Return a usable logger, configuring a default one if needed."""
	if logger is not None:
		return logger
	if not _module_logger.handlers:
		_module_logger.setLevel(logging.INFO)
		_module_logger.addHandler(logging.StreamHandler(sys.stdout))
	return _module_logger


def get_public_addresses(
    urls: Mapping[str, str] = IPIFY_URLS,
    session: Optional[requests.Session] = None,
    logger: Optional[logging.Logger] = None,
) -> dict:
	"""Return a mapping of placeholder name to current public IP address.

	Addresses that cannot be retrieved are simply omitted from the result
	rather than raising, so that an unreachable IPv6 endpoint does not
	prevent IPv4 records from being updated (and vice versa).
	"""
	logger = _ensure_logger(logger)
	get = session.get if session is not None else requests.get

	logger.debug("Retrieving current addresses from ipify.org")
	addresses: dict = {}
	for name, url in urls.items():
		try:
			response = get(url, timeout = HTTP_TIMEOUT)
			response.raise_for_status()
			address = response.json()["ip"]
		except (requests.RequestException, ValueError, KeyError):
			logger.warning("Could not retrieve {%s}", name)
			continue
		logger.info("Current {%s} is: %s", name, address)
		addresses[name] = address
	return addresses


def _candidate_global_ipv6(
    interface: Optional[str] = None,
    *,
    proc_path: str = PROC_NET_IF_INET6,
    logger: Optional[logging.Logger] = None,
) -> List[str]:
	"""Return the host's stable global IPv6 addresses, best candidate first.

	Reads Linux' ``/proc/net/if_inet6`` and keeps only internet-routable global
	unicast addresses that are not temporary (RFC 4941), tentative or
	DAD-failed. Candidates are ranked preferring permanent and non-deprecated
	addresses so the most appropriate one for a DNS record comes first.

	Returns an empty list (and warns) on hosts without ``/proc/net/if_inet6``
	(e.g. non-Linux) or when no suitable address exists.
	"""
	logger = _ensure_logger(logger)

	try:
		with open(proc_path) as source:
			lines = source.readlines()
	except OSError:
		logger.warning(
		    "Cannot read %s; local IPv6 discovery is unavailable on this host",
		    proc_path
		)
		return []

	candidates = []  # (not_permanent, deprecated, devname, address)
	for line in lines:
		fields = line.split()
		if len(fields) < 6:
			continue
		raw_addr, _ifindex, _prefixlen, raw_scope, raw_flags, devname = fields[:6]

		if interface is not None and devname != interface:
			continue

		try:
			scope = int(raw_scope, 16)
			flags = int(raw_flags, 16)
			address = ipaddress.IPv6Address(int(raw_addr, 16))
		except ValueError:
			continue

		if scope != IPV6_SCOPE_GLOBAL or not address.is_global:
			continue
		if flags & _IFA_F_UNUSABLE:
			continue

		candidates.append((
		    not flags & IFA_F_PERMANENT,
		    bool(flags & IFA_F_DEPRECATED),
		    devname,
		    str(address),
		))

	if not candidates:
		logger.warning(
		    "No stable global IPv6 address found%s",
		    " on interface {}".format(interface) if interface else ""
		)
		return []

	candidates.sort()
	return [address for *_, address in candidates]


def get_global_ipv6(
    interface: Optional[str] = None,
    *,
    proc_path: str = PROC_NET_IF_INET6,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
	"""Return the host's best stable global IPv6 address, or ``None``.

	Convenience accessor returning the top candidate from
	:func:`_candidate_global_ipv6` without any external verification.
	"""
	candidates = _candidate_global_ipv6(
	    interface, proc_path = proc_path, logger = logger
	)
	return candidates[0] if candidates else None


class _SourceAddressAdapter(requests.adapters.HTTPAdapter):
	"""HTTP adapter that binds outgoing connections to a fixed source address."""

	def __init__(self, source_address: str, **kwargs):
		self._source_address = (source_address, 0)
		super().__init__(**kwargs)

	def init_poolmanager(self, *args, **kwargs):
		kwargs["source_address"] = self._source_address
		super().init_poolmanager(*args, **kwargs)


def _ipify_sees(
    address: str,
    *,
    url: str = IPIFY_URLS["remote_addr6"],
    timeout: int = HTTP_TIMEOUT,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
	"""Return the address ipify reports when egressing from ``address``.

	Binds the request's source socket to ``address`` so ipify observes that
	exact address (when it is routable). Returns ``None`` when ipify cannot be
	reached from that source.
	"""
	logger = _ensure_logger(logger)
	session = requests.Session()
	session.mount("https://", _SourceAddressAdapter(address))
	try:
		response = session.get(url, timeout = timeout)
		response.raise_for_status()
		return response.json()["ip"]
	except (requests.RequestException, ValueError, KeyError):
		return None
	finally:
		session.close()


def resolve_ipv6(
    interface: Optional[str] = None,
    *,
    verify: bool = True,
    proc_path: str = PROC_NET_IF_INET6,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
	"""Return the canonical global IPv6 address to advertise, or ``None``.

	Picks among the host's stable global addresses (see
	:func:`_candidate_global_ipv6`). When ``verify`` is set, each candidate is
	checked against ipify on a best-effort basis: the address ipify confirms is
	used; an address ipify *disagrees* with is rejected; and if ipify cannot be
	reached at all, the best local candidate is used anyway so that an ipify
	outage never blocks IPv6 updates.
	"""
	logger = _ensure_logger(logger)
	candidates = _candidate_global_ipv6(
	    interface, proc_path = proc_path, logger = logger
	)
	if not candidates:
		return None
	if not verify:
		return candidates[0]

	unreachable = []
	for address in candidates:
		seen = _ipify_sees(address, logger = logger)
		if seen is None:
			logger.debug("Could not reach ipify from %s to verify", address)
			unreachable.append(address)
			continue
		if seen == address:
			logger.info("Verified global IPv6 %s via ipify", address)
			return address
		logger.warning(
		    "ipify reports %s when using %s as source; trying next candidate",
		    seen, address
		)

	if unreachable:
		address = unreachable[0]
		logger.warning(
		    "Could not verify IPv6 via ipify (unreachable); "
		    "using local stable address %s", address
		)
		return address

	logger.warning(
	    "No global IPv6 address agreed with ipify; skipping AAAA record"
	)
	return None


def resolve_addresses(
    session: Optional[requests.Session] = None,
    interface: Optional[str] = None,
    *,
    verify_ipv6: bool = True,
    logger: Optional[logging.Logger] = None,
) -> dict:
	"""Return the placeholder-to-address mapping used to fill record values.

	``remote_addr`` (IPv4) comes from ipify, while ``remote_addr6`` (IPv6) is
	discovered from the host's local interfaces (see :func:`resolve_ipv6`).
	Addresses that cannot be determined are simply omitted.
	"""
	logger = _ensure_logger(logger)

	addresses = get_public_addresses(
	    urls = {"remote_addr": IPIFY_URLS["remote_addr"]},
	    session = session,
	    logger = logger,
	)

	address6 = resolve_ipv6(interface, verify = verify_ipv6, logger = logger)
	if address6 is not None:
		addresses["remote_addr6"] = address6
		logger.info("Current {remote_addr6} is: %s", address6)

	return addresses


def _required_placeholders(values: Mapping) -> set:
	"""Return the set of ``{placeholder}`` names referenced by ``values``."""
	required = set()
	formatter = string.Formatter()
	for value in values:
		for _literal, field, _spec, _conv in formatter.parse(value):
			if field:
				required.add(field)
	return required


def _format_record(record: Mapping, addresses: Mapping[str, str]) -> dict:
	"""Return a copy of ``record`` with its ``rrset_values`` formatted.

	The input record is never mutated.
	"""
	formatted = deepcopy(dict(record))
	formatted["rrset_values"] = [
	    value.format(**addresses) for value in record.get("rrset_values", [])
	]
	return formatted


def _authorization_header(
    apikey: Optional[str], token: Optional[str]
) -> str:
	"""Return the value of the Gandi ``Authorization`` header.

	Gandi's ``api.gandi.net`` endpoint authenticates with an ``Authorization``
	header: ``Bearer`` for a Personal Access Token (PAT) and ``Apikey`` for a
	legacy API key.
	"""
	if token:
		return "Bearer {}".format(token)
	if apikey:
		return "Apikey {}".format(apikey)
	raise ValueError("an apikey or a token is required to authenticate")


def gandyndns(
    domain: str,
    apikey: Optional[str] = None,
    records: Optional[Mapping[str, Mapping[str, Mapping]]] = None,
    logger: Optional[logging.Logger] = None,
    *,
    token: Optional[str] = None,
    addresses: Optional[Mapping[str, str]] = None,
    interface: Optional[str] = None,
    verify_ipv6: bool = True,
    api_url: str = GANDI_API_URL,
    session: Optional[requests.Session] = None,
) -> bool:
	"""Synchronise ``records`` of ``domain`` with the current public IP.

	Authentication uses ``token`` (a Gandi Personal Access Token) when given,
	otherwise ``apikey`` (a legacy Gandi API key).

	When ``addresses`` is not supplied it is resolved via
	:func:`resolve_addresses` (``interface`` and ``verify_ipv6`` tune the IPv6
	discovery). A record whose values reference an address that could not be
	determined is skipped with a warning rather than failing the whole run.

	Returns ``True`` when every record is either already up to date or was
	updated successfully, ``False`` otherwise.
	"""
	logger = _ensure_logger(logger)
	records = records or {}

	if addresses is None:
		addresses = resolve_addresses(
		    session = session,
		    interface = interface,
		    verify_ipv6 = verify_ipv6,
		    logger = logger,
		)

	api = session if session is not None else requests.Session()
	api.headers.update({
	    "Authorization": _authorization_header(apikey, token),
	    "Content-Type": "application/json",
	})

	success = True

	for record_name, record_types in records.items():
		for record_type, record in record_types.items():
			missing = _required_placeholders(record.get("rrset_values", [])
			                                ) - set(addresses)
			if missing:
				logger.warning(
				    "Skipping record %r of domain %r: address(es) %s unavailable",
				    record_name, domain, ", ".join(sorted(missing))
				)
				continue

			record = _format_record(record, addresses)

			url = "{}/domains/{}/records/{}/{}".format(
			    api_url, domain, record_name, record_type
			)

			response = api.get(url)
			data = response.json()

			if response.status_code not in (200, 404):
				logger.error(
				    "Could not retrieve record %r of domain %r: %s",
				    record_name, domain, data
				)
				success = False
				continue

			if data.get("rrset_values", []) == record.get("rrset_values", []):
				logger.info(
				    "Record %r of domain %r is up to date!", record_name,
				    domain
				)
				continue

			data.update(record)
			response = api.put(url, json = data)
			data = response.json()

			if response.status_code in (200, 201):
				logger.info(
				    "Record %r of domain %r has been updated: %s", record_name,
				    domain, data.get("message")
				)
			else:
				logger.error(
				    "Could not update record %r of domain %r: %s", record_name,
				    domain, data.get("errors", data)
				)
				success = False

	return success
