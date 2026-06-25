import json
import logging

import responses

from gandyndns import cli, core

LOGGER = logging.getLogger("gandyndns.tests")


def test_load_config_explicit_path(tmp_path):
	config = {"domains": {"example.com": {}}}
	path = tmp_path / "gandyndns.json"
	path.write_text(json.dumps(config))

	assert cli.load_config(path, logger = LOGGER) == config


def test_load_config_missing_explicit_path_raises(tmp_path):
	missing = tmp_path / "does-not-exist.json"
	try:
		cli.load_config(missing, logger = LOGGER)
	except FileNotFoundError:
		pass
	else:  # pragma: no cover
		raise AssertionError("expected FileNotFoundError")


def test_load_config_searches_candidate_paths(tmp_path, monkeypatch):
	found = tmp_path / "gandyndns.json"
	config = {"domains": {}}
	found.write_text(json.dumps(config))

	monkeypatch.setattr(
	    cli, "candidate_config_paths", lambda: iter([
	        tmp_path / "missing.json",
	        found,
	    ])
	)

	assert cli.load_config(logger = LOGGER) == config


def test_load_config_no_file_found_raises(tmp_path, monkeypatch):
	monkeypatch.setattr(
	    cli, "candidate_config_paths", lambda: iter([tmp_path / "nope.json"])
	)
	try:
		cli.load_config(logger = LOGGER)
	except FileNotFoundError:
		pass
	else:  # pragma: no cover
		raise AssertionError("expected FileNotFoundError")


def test_build_logger_defaults_to_stdout():
	logger = logging.getLogger("gandyndns")
	logger.handlers.clear()

	built = cli.build_logger(logging.DEBUG, "stdout")

	assert built.level == logging.DEBUG
	assert any(isinstance(h, logging.StreamHandler) for h in built.handlers)


def test_build_logger_file_handler(tmp_path):
	logger = logging.getLogger("gandyndns")
	logger.handlers.clear()
	log_path = tmp_path / "gandyndns.log"

	built = cli.build_logger(logging.INFO, "file:{}".format(log_path))

	assert any(
	    isinstance(h, logging.FileHandler) for h in built.handlers
	)
	logging.getLogger("gandyndns").handlers.clear()


def test_parse_args_positional_and_option(tmp_path):
	args = cli.parse_args(["/path/to/config.json"])
	assert str(args.config_path) == "/path/to/config.json"
	assert args.config is None

	args = cli.parse_args(["-c", "/other.json"])
	assert str(args.config) == "/other.json"


@responses.activate
def test_main_runs_end_to_end(tmp_path):
	logging.getLogger("gandyndns").handlers.clear()

	config = {
	    "domains": {
	        "example.com": {
	            "apikey": "secret",
	            "records": {
	                "test": {
	                    "A": {"rrset_values": ["{remote_addr}"]},
	                },
	            },
	        },
	    },
	}
	config_path = tmp_path / "gandyndns.json"
	config_path.write_text(json.dumps(config))

	responses.get(core.IPIFY_URLS["remote_addr"], json = {"ip": "203.0.113.7"})
	responses.get(core.IPIFY_URLS["remote_addr6"], status = 500)
	record_url = "{}/domains/example.com/records/test/A".format(
	    core.GANDI_API_URL
	)
	responses.get(record_url, json = {"rrset_values": ["1.2.3.4"]}, status = 200)
	responses.put(record_url, json = {"message": "updated"}, status = 200)

	exit_code = cli.main(["-c", str(config_path)])

	assert exit_code == 0
	assert responses.calls[-1].request.method == "PUT"
	sent = json.loads(responses.calls[-1].request.body)
	assert sent["rrset_values"] == ["203.0.113.7"]
