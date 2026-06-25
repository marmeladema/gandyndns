import logging

import pytest
import requests
import responses

from gandyndns import core
from gandyndns.core import (
    gandyndns,
    get_global_ipv6,
    get_public_addresses,
    resolve_addresses,
    resolve_ipv6,
)

LOGGER = logging.getLogger("gandyndns.tests")

# A realistic /proc/net/if_inet6 snapshot. Columns are:
#   address(32 hex)  ifindex  prefixlen  scope  flags  devname
# Addresses (after normalisation):
#   2a01:e0a:1234:5678::1  eth0   permanent, global        <- canonical
#   2a01:e0a:1234:5678:dead:beef:cafe:2  eth0  temporary   <- excluded (0x01)
#   2a01:e0a:1234:5678::3  eth0   permanent+deprecated      <- lower priority
#   2a01:e0a:1234:5678::4  eth0   tentative                 <- excluded (0x40)
#   2a01:e0a:1234:5678::5  wlan0  permanent, global         <- other iface
#   fe80::1                eth0   link-local                <- excluded (scope)
#   fd12:3456:789a:1::1    eth0   permanent, ULA            <- excluded (!global)
PROC_IF_INET6 = (
    "2a010e0a123456780000000000000001 02 40 00 80     eth0\n"
    "2a010e0a12345678deadbeefcafe0002 02 40 00 01     eth0\n"
    "2a010e0a123456780000000000000003 02 40 00 a0     eth0\n"
    "2a010e0a123456780000000000000004 02 40 00 40     eth0\n"
    "2a010e0a123456780000000000000005 03 40 00 80     wlan0\n"
    "fe800000000000000000000000000001 02 40 20 80     eth0\n"
    "fd123456789a00010000000000000001 02 40 00 80     eth0\n"
)

ADDR_CANONICAL = "2a01:e0a:1234:5678::1"
ADDR_DEPRECATED = "2a01:e0a:1234:5678::3"
ADDR_WLAN = "2a01:e0a:1234:5678::5"


@pytest.fixture
def proc_if_inet6(tmp_path):
	path = tmp_path / "if_inet6"
	path.write_text(PROC_IF_INET6)
	return str(path)


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


# ---------------------------------------------------------------------------
# IPv6 interface discovery
# ---------------------------------------------------------------------------


def test_candidate_global_ipv6_ranks_and_filters(proc_if_inet6):
	candidates = core._candidate_global_ipv6(
	    proc_path = proc_if_inet6, logger = LOGGER
	)

	# Permanent non-deprecated first, deprecated last; temporary, tentative,
	# link-local and ULA excluded.
	assert candidates == [ADDR_CANONICAL, ADDR_WLAN, ADDR_DEPRECATED]


def test_get_global_ipv6_returns_best_candidate(proc_if_inet6):
	assert get_global_ipv6(
	    proc_path = proc_if_inet6, logger = LOGGER
	) == ADDR_CANONICAL


def test_candidate_global_ipv6_interface_filter(proc_if_inet6):
	assert core._candidate_global_ipv6(
	    "wlan0", proc_path = proc_if_inet6, logger = LOGGER
	) == [ADDR_WLAN]


def test_get_global_ipv6_missing_proc_returns_none(tmp_path):
	missing = str(tmp_path / "does-not-exist")
	assert get_global_ipv6(proc_path = missing, logger = LOGGER) is None


def test_candidate_global_ipv6_no_stable_address(tmp_path):
	# Only a temporary and a link-local address: nothing to advertise.
	path = tmp_path / "if_inet6"
	path.write_text(
	    "2a010e0a123456780000000000000009 02 40 00 01     eth0\n"
	    "fe800000000000000000000000000001 02 40 20 80     eth0\n"
	)
	assert core._candidate_global_ipv6(
	    proc_path = str(path), logger = LOGGER
	) == []


# ---------------------------------------------------------------------------
# Best-effort ipify verification
# ---------------------------------------------------------------------------


def test_resolve_ipv6_returns_verified_candidate(monkeypatch):
	monkeypatch.setattr(
	    core, "_candidate_global_ipv6",
	    lambda *a, **k: [ADDR_CANONICAL, ADDR_WLAN]
	)
	monkeypatch.setattr(core, "_ipify_sees", lambda address, **k: address)

	assert resolve_ipv6(logger = LOGGER) == ADDR_CANONICAL


def test_resolve_ipv6_skips_disagreeing_candidate(monkeypatch):
	monkeypatch.setattr(
	    core, "_candidate_global_ipv6",
	    lambda *a, **k: [ADDR_CANONICAL, ADDR_WLAN]
	)
	# ipify sees something else for the first candidate, agrees on the second.
	seen = {ADDR_CANONICAL: "2a01:e0a:1234:5678::ff", ADDR_WLAN: ADDR_WLAN}
	monkeypatch.setattr(core, "_ipify_sees", lambda address, **k: seen[address])

	assert resolve_ipv6(logger = LOGGER) == ADDR_WLAN


def test_resolve_ipv6_falls_back_when_ipify_unreachable(monkeypatch):
	monkeypatch.setattr(
	    core, "_candidate_global_ipv6",
	    lambda *a, **k: [ADDR_CANONICAL, ADDR_WLAN]
	)
	monkeypatch.setattr(core, "_ipify_sees", lambda address, **k: None)

	# An ipify outage must not block IPv6: use the best local candidate.
	assert resolve_ipv6(logger = LOGGER) == ADDR_CANONICAL


def test_resolve_ipv6_skips_when_all_disagree(monkeypatch):
	monkeypatch.setattr(
	    core, "_candidate_global_ipv6",
	    lambda *a, **k: [ADDR_CANONICAL, ADDR_WLAN]
	)
	monkeypatch.setattr(
	    core, "_ipify_sees", lambda address, **k: "2a01:e0a:1234:5678::ff"
	)

	assert resolve_ipv6(logger = LOGGER) is None


def test_resolve_ipv6_without_verification(monkeypatch):
	monkeypatch.setattr(
	    core, "_candidate_global_ipv6", lambda *a, **k: [ADDR_CANONICAL]
	)

	def _fail(*a, **k):  # pragma: no cover - must not be called
		raise AssertionError("ipify must not be queried when verify=False")

	monkeypatch.setattr(core, "_ipify_sees", _fail)

	assert resolve_ipv6(verify = False, logger = LOGGER) == ADDR_CANONICAL


@responses.activate
def test_ipify_sees_returns_reported_address():
	responses.get(core.IPIFY_URLS["remote_addr6"], json = {"ip": ADDR_CANONICAL})

	assert core._ipify_sees(ADDR_CANONICAL, logger = LOGGER) == ADDR_CANONICAL


@responses.activate
def test_ipify_sees_returns_none_when_unreachable():
	responses.add(
	    responses.GET,
	    core.IPIFY_URLS["remote_addr6"],
	    body = requests.exceptions.ConnectionError("unreachable"),
	)

	assert core._ipify_sees(ADDR_CANONICAL, logger = LOGGER) is None


def test_source_address_adapter_binds_source():
	adapter = core._SourceAddressAdapter(ADDR_CANONICAL)
	assert adapter.poolmanager.connection_pool_kw["source_address"] == (
	    ADDR_CANONICAL, 0
	)


# ---------------------------------------------------------------------------
# resolve_addresses + record skipping
# ---------------------------------------------------------------------------


@responses.activate
def test_resolve_addresses_combines_ipv4_and_ipv6(monkeypatch):
	responses.get(core.IPIFY_URLS["remote_addr"], json = {"ip": "203.0.113.1"})
	monkeypatch.setattr(core, "resolve_ipv6", lambda *a, **k: ADDR_CANONICAL)

	addresses = resolve_addresses(logger = LOGGER)

	assert addresses == {
	    "remote_addr": "203.0.113.1",
	    "remote_addr6": ADDR_CANONICAL,
	}


@responses.activate
def test_record_skipped_when_address_unavailable(caplog):
	# IPv4 record updates; AAAA record is skipped because remote_addr6 is absent.
	responses.get(
	    _record_url(rtype = "A"),
	    json = {"rrset_values": ["203.0.113.1"]},
	    status = 200,
	)

	records = {
	    "test": {
	        "A": {"rrset_values": ["{remote_addr}"]},
	        "AAAA": {"rrset_values": ["{remote_addr6}"]},
	    }
	}

	with caplog.at_level(logging.WARNING, logger = "gandyndns.tests"):
		success = gandyndns(
		    "example.com",
		    "apikey",
		    records,
		    logger = LOGGER,
		    addresses = {"remote_addr": "203.0.113.1"},
		)

	assert success is True
	assert "Skipping record" in caplog.text
	# Only the IPv4 record triggered an HTTP call (a single GET, already current).
	assert len(responses.calls) == 1
	assert "/records/test/A" in responses.calls[0].request.url
