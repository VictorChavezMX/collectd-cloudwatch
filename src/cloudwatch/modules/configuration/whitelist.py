import re
from os import path
from string import strip
from threading import Lock

from configreader import ConfigReader
from ..logger.logger import get_logger


class WhitelistConfigReader(object):
    """
    The WhitelistReader is responsible for parsing the whitelist.conf file into a whitelist regex list
    used by the Whitelist class. During this process the syntax of each line from whitelist.conf is validated.
    Any line that is not a valid regex will be logged and ignored.
    """
    _LOGGER = get_logger(__name__)
    NO_SUCH_FILE = 2
    START_STRING = "^"
    END_STRING = "$"
    EMPTY_REGEX = START_STRING + END_STRING

    PASS_THROUGH_REGEX_STRING = "^\.[\*\+]?\s.*$|^.*?\s\.[\*\+]|^\.[\*\+]$"  # matches single .*, .+ strings
    # as well as  strings with .* or .+ preceded or followed by whitespace.

    def __init__(self, whitelist_config_path, pass_through_allowed):
        self.whitelist_config_path = whitelist_config_path
        self.pass_through_allowed = pass_through_allowed
        self.pass_through_regex = re.compile(self.PASS_THROUGH_REGEX_STRING)

    def get_regex_list(self):
        """
        Reads whitelist configuration file and returns a single string with compound regex.
        :return: regex string used to test if metric is whitelisted
        """
        try:
            return self._get_whitelisted_names_from_file(self.whitelist_config_path)
        except IOError as e:
            if e.errno is self.NO_SUCH_FILE:
                self._create_whitelist_file(self.whitelist_config_path)
            else:
                self._LOGGER.warning("Could not open whitelist file '" + self.whitelist_config_path + "'. Reason: " + str(e))
            return [self.EMPTY_REGEX]

    def _get_whitelisted_names_from_file(self, whitelist_path):
        with open(whitelist_path) as whitelist_file:
            return self._filter_valid_regexes(map(strip, whitelist_file))

    def _create_whitelist_file(self, whitelist_path):
        if not path.exists(whitelist_path):
            self._LOGGER.warning("The whitelist configuration file was not detected at " +
                                 whitelist_path + ". Creating new file.")
            with open(whitelist_path, 'w') as whitelist_file:
                whitelist_file.write("")

    def _filter_valid_regexes(self, regex_list):
        valid_regexes = [self._decorate_regex_line(line) for line in regex_list if self._is_valid_regex(line)]
        return valid_regexes or [self.EMPTY_REGEX]

    def _is_valid_regex(self, regex_string):
        try:
            if self._is_allowed_regex(regex_string):
                re.compile(self._decorate_regex_line(regex_string))
                return True
            return False
        except Exception as e:
            self._LOGGER.warning("The whitelist rule: '{0}' is invalid, reason: {1}".format(str(regex_string), str(e.message)))
            return False

    def _is_allowed_regex(self, regex_string):
        if self.pass_through_allowed:
            return True
        if self.pass_through_regex.match(regex_string):
            self._LOGGER.warning("The unsafe whitelist rule: '{0}' was disabled. "
                                 "Revisit the rule or change {1} option in the plugin configuration.".format(regex_string, ConfigReader.PASS_THROUGH_CONFIG_KEY))
            return False
        return True

    def _decorate_regex_line(self, line):
        return self.START_STRING + str(line).strip() + self.END_STRING


class BlockedMetricLogger(object):
    """
    The BlockedMetricLoger maintains a separate log of metrics that are rejected by the whitelist.
    The log will be recreated on plugin startup to ensure that it contains the most recent metrics.
    """
    _LOGGER = get_logger(__name__)
    BLOCKED_LOG_HEADER = "# This file is automatically generated - do not modify this file.\
    \n# Use this file to find metrics to be added to the whitelist file instead.\n"

    def __init__(self, log_path):
        self._log_path = log_path
        self._lock = Lock()
        self._create_log()

    def _create_log(self):
        try:
            with self._lock:
                with open(self._log_path, 'w') as blocked_file:
                    blocked_file.write(self.BLOCKED_LOG_HEADER)
        except IOError as e:
            self._LOGGER.warning("Could not create list of blocked metrics '" + self._log_path +
                                 "'. Reason: " + str(e))

    def log_metric(self, metric_name):
        try:
            with self._lock:
                with open(self._log_path, 'a') as blocked_file:
                    blocked_file.write(metric_name + "\n")
        except IOError as e:
            self._LOGGER.warning("Could not update list of blocked metrics '" + self._log_path +
                                 "' with metric: '" + metric_name + "'. Reason: " + str(e))


class Whitelist(object):
    """
    The Whitelist is responsible for testing whether a metric should be published or not.
    Whitelist object will run regex test against each unique metric only once, after this a cached result will be used.
    Blocked metrics are also automatically written to a separate log file.
    """
    _LOGGER = get_logger(__name__)

    def __init__(self, whitelist_regex_list, blocked_metric_log_path):
        self.blocked_metric_log = BlockedMetricLogger(blocked_metric_log_path)
        self._whitelist_regex = re.compile("|".join(whitelist_regex_list))
        self._allowed_metrics = {}

    def is_whitelisted(self, metric_key):
        """
        Checks whether metric should be emitted or not. All unique metrics that are blocked will also be logged.
        :param metric_key: string describing all parts that make the actual name of a collectd metric
        :return: True if test is positive, False otherwise.
        """
        if metric_key not in self._allowed_metrics:
            if self._whitelist_regex.match(metric_key):
                self._allowed_metrics[metric_key] = True
            else:
                self._allowed_metrics[metric_key] = False
                self.blocked_metric_log.log_metric(metric_key)
        return self._allowed_metrics[metric_key]



