"""Core logic for gandyndns.

Update Gandi LiveDNS records so that they match the machine's current
public IP address(es).
"""

from __future__ import annotations

import logging
import sys
from copy import deepcopy
from typing import Mapping, MutableMapping, Optional

import requests

# Base URL of the Gandi LiveDNS REST API.
GANDI_API_URL = "https://api.gandi.net/v5/livedns"

# Services used to discover the machine's current public IP addresses,
# keyed by the placeholder name that can be used in record values.
IPIFY_URLS = {
	"remote_addr": "https://api.ipify.org/?format=json",
	"remote_addr6": "https://api6.ipify.org/?format=json",
}

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
			response = get(url)
			response.raise_for_status()
			address = response.json()["ip"]
		except (requests.RequestException, ValueError, KeyError):
			logger.warning("Could not retrieve {%s}", name)
			continue
		logger.info("Current {%s} is: %s", name, address)
		addresses[name] = address
	return addresses


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
    api_url: str = GANDI_API_URL,
    session: Optional[requests.Session] = None,
) -> bool:
	"""Synchronise ``records`` of ``domain`` with the current public IP.

	Authentication uses ``token`` (a Gandi Personal Access Token) when given,
	otherwise ``apikey`` (a legacy Gandi API key).

	Returns ``True`` when every record is either already up to date or was
	updated successfully, ``False`` otherwise.
	"""
	logger = _ensure_logger(logger)
	records = records or {}

	if addresses is None:
		addresses = get_public_addresses(session = session, logger = logger)

	api = session if session is not None else requests.Session()
	api.headers.update({
	    "Authorization": _authorization_header(apikey, token),
	    "Content-Type": "application/json",
	})

	success = True

	for record_name, record_types in records.items():
		for record_type, record in record_types.items():
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
