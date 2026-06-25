"""Command-line interface for gandyndns."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import platform
import sys
from pathlib import Path
from typing import Iterator, Optional, Sequence

import platformdirs

from .core import gandyndns

APPNAME = "gandyndns"
CONFIG_FILENAME = "gandyndns.json"


def candidate_config_paths() -> Iterator[Path]:
	"""Yield candidate configuration file paths in priority order."""
	user_dirs = platformdirs.user_config_dir(APPNAME)
	site_dirs = platformdirs.site_config_dir(APPNAME, multipath = True)
	for config_dir in (user_dirs + os.pathsep + site_dirs).split(os.pathsep):
		if config_dir:
			yield Path(config_dir) / CONFIG_FILENAME


def load_config(
    config_path: Optional[os.PathLike] = None,
    logger: Optional[logging.Logger] = None,
) -> dict:
	"""Load and return the gandyndns configuration.

	When ``config_path`` is given it is loaded directly; otherwise the
	standard per-user and system configuration directories are searched.
	Raises ``FileNotFoundError`` when no configuration file can be found.
	"""
	logger = logger or logging.getLogger("gandyndns")

	if config_path is not None:
		path = Path(config_path)
		logger.debug("Loading configuration file: %s", path)
		with open(path) as source:
			config = json.load(source)
		logger.info("Loaded configuration file: %s", path)
		return config

	for path in candidate_config_paths():
		try:
			source = open(path)
		except OSError:
			logger.debug("Could not load configuration file: %s", path)
			continue
		with source:
			config = json.load(source)
		logger.info("Loaded configuration file: %s", path)
		return config

	raise FileNotFoundError("No gandyndns configuration file found")


def build_logger(level: int, handler_spec: str) -> logging.Logger:
	"""Build the ``gandyndns`` logger from CLI options."""
	logger = logging.getLogger("gandyndns")
	logger.setLevel(level)

	name, _, argument = handler_spec.partition(":")
	if name == "file":
		handler: logging.Handler = logging.FileHandler(argument)
	elif name == "syslog":
		handler = logging.handlers.SysLogHandler()
	else:  # "stdout" and any unknown handler fall back to stdout.
		handler = logging.StreamHandler(sys.stdout)

	logger.addHandler(handler)
	return logger


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(
	    prog = APPNAME,
	    description = "Update Gandi LiveDNS records with the current public IP.",
	)
	parser.add_argument(
	    "config_path",
	    nargs = "?",
	    type = Path,
	    help = "Path to the gandyndns configuration file.",
	)
	parser.add_argument(
	    "-c",
	    "--config",
	    dest = "config",
	    type = Path,
	    help = "Path to the gandyndns configuration file (overrides positional).",
	)
	parser.add_argument(
	    "--logging-level",
	    type = int,
	    default = logging.INFO,
	    help = "Logging level (default: %(default)s).",
	)
	parser.add_argument(
	    "--logging-handler",
	    default = "stdout",
	    help = "Logging handler: stdout, file:PATH or syslog (default: stdout).",
	)
	return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
	if platform.system() == "Linux":
		os.environ.setdefault("XDG_CONFIG_DIRS", "/etc:/usr/local/etc")

	args = parse_args(argv)
	logger = build_logger(args.logging_level, args.logging_handler)

	config = load_config(args.config or args.config_path, logger = logger)
	logger.debug(config)

	success = True
	for domain, domain_config in config.get("domains", {}).items():
		domain_config = dict(domain_config)
		domain_config["logger"] = logger
		success = gandyndns(domain, **domain_config) and success

	return 0 if success else 1


if __name__ == "__main__":
	sys.exit(main())
