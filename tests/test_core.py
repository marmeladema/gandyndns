import logging

import pytest
import responses

from gandyndns import core
from gandyndns.core import gandyndns, get_public_addresses

LOGGER = logging.getLogger("gandyndns.tests")


@responses.activate
def test_get_public_addresses_returns_both_families():
	responses.get(core.IPIFY_URLS["remote_addr"], json = {"ip": "203.0.113.1"})
	responses.get(core.IPIFY_URLS["remote_addr6"], json = {"ip": "2001:db8::1"})

	addresses = get_public_addresses(logger = LOGGER)

	assert addresses == {
	    "remote_addr": "203.0.113.1",
	    "remote_addr6": "2001:db8::1",
	}


@responses.activate
def test_get_public_addresses_skips_unreachable_endpoint():
	responses.get(core.IPIFY_URLS["remote_addr"], json = {"ip": "203.0.113.1"})
	responses.get(core.IPIFY_URLS["remote_addr6"], status = 500)

	addresses = get_public_addresses(logger = LOGGER)

	assert addresses == {"remote_addr": "203.0.113.1"}


def _record_url(domain = "example.com", name = "test", rtype = "A"):
	return "{}/domains/{}/records/{}/{}".format(
	    core.GANDI_API_URL, domain, name, rtype
	)


@responses.activate
def test_up_to_date_record_is_not_updated():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["203.0.113.1"]},
	    status = 200,
	)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	success = gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert success is True
	# Only the GET was issued, no PUT.
	assert len(responses.calls) == 1
	assert responses.calls[0].request.method == "GET"


@responses.activate
def test_missing_record_is_created():
	responses.get(_record_url(), json = {}, status = 404)
	put = responses.put(
	    _record_url(),
	    json = {"message": "DNS Record Created"},
	    status = 201,
	)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	success = gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert success is True
	assert put.call_count == 1
	import json
	sent = json.loads(responses.calls[1].request.body)
	assert sent["rrset_values"] == ["203.0.113.1"]


@responses.activate
def test_stale_record_is_updated():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["198.51.100.9"]},
	    status = 200,
	)
	responses.put(_record_url(), json = {"message": "updated"}, status = 200)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	success = gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert success is True
	assert responses.calls[-1].request.method == "PUT"


@responses.activate
def test_failed_update_reports_failure():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["198.51.100.9"]},
	    status = 200,
	)
	responses.put(_record_url(), json = {"errors": ["nope"]}, status = 403)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	success = gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert success is False


@responses.activate
def test_failed_retrieval_reports_failure():
	responses.get(_record_url(), json = {"error": "boom"}, status = 500)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	success = gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert success is False


@responses.activate
def test_apikey_is_sent_as_authorization_apikey():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["203.0.113.1"]},
	    status = 200,
	)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	gandyndns(
	    "example.com",
	    "my-api-key",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert responses.calls[0].request.headers["Authorization"] == "Apikey my-api-key"


@responses.activate
def test_token_is_sent_as_authorization_bearer():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["203.0.113.1"]},
	    status = 200,
	)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	gandyndns(
	    "example.com",
	    records = records,
	    logger = LOGGER,
	    token = "my-pat",
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	assert responses.calls[0].request.headers["Authorization"] == "Bearer my-pat"


def test_missing_credentials_raises():
	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	with pytest.raises(ValueError):
		gandyndns(
		    "example.com",
		    records = records,
		    logger = LOGGER,
		    addresses = {"remote_addr": "203.0.113.1"},
		)


@responses.activate
def test_input_records_are_not_mutated():
	responses.get(
	    _record_url(),
	    json = {"rrset_values": ["203.0.113.1"]},
	    status = 200,
	)

	records = {"test": {"A": {"rrset_values": ["{remote_addr}"]}}}
	gandyndns(
	    "example.com",
	    "apikey",
	    records,
	    logger = LOGGER,
	    addresses = {"remote_addr": "203.0.113.1"},
	)

	# The caller's template must remain untouched.
	assert records["test"]["A"]["rrset_values"] == ["{remote_addr}"]
