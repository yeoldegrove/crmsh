# -*- coding: utf-8 -*-

import os
import sys
import socket
import shutil
import logging
import logging.config
from contextlib import contextmanager

from . import options
from . import constants


CRMSH_LOG_FILE = "/var/log/crmsh/crmsh.log"


class ConsoleCustomHandler(logging.StreamHandler):
    """
    A custom handler for console

    Redirect ERROR message to sys.stderr
    Redirect INFO/WARNING/DEBUG message to sys.stdout
    """

    def emit(self, record):
        if record.levelno < logging.ERROR:
            stream = sys.stdout
        else:
            stream = sys.stderr
        msg = self.format(record)
        stream.write(msg)
        stream.write(self.terminator)


class ConsoleCustomFormatter(logging.Formatter):
    """
    A custom formatter for console

    Wrap levelname with colors
    Wrap message with line number which is used for regression test
    """
    COLORS = {
        "WARNING": constants.YELLOW,
        "INFO": constants.GREEN,
        "ERROR": constants.RED
    }
    FORMAT = "%(levelname)s: %(message)s"
    FORMAT_RAW = "%(message)s"

    def __init__(self, lineno=-1, raw_msg=False, fmt=None):
        self.lineno = lineno
        if fmt:
            super().__init__(fmt=fmt)
        elif raw_msg:
            super().__init__(fmt=self.FORMAT_RAW)
        else:
            super().__init__(fmt=self.FORMAT)

    def format(self, record):
        levelname = record.levelname
        # wrap with colors
        if levelname in self.COLORS and not options.regression_tests:
            record.levelname = self.COLORS[levelname] + levelname + constants.END
        # wrap with line number
        if self.lineno > 0:
            msg = record.msg
            record.msg = "{}: {}".format(self.lineno, msg)
            record.levelname = levelname
        return super().format(record)


class ConsoleReportFormatter(ConsoleCustomFormatter):
    """
    Custom formatter for crm report
    """
    FORMAT_REPORT = "{}: %(levelname)s: %(message)s".format(socket.gethostname())

    def __init__(self):
        super().__init__(fmt=self.FORMAT_REPORT)


class FileCustomFormatter(logging.Formatter):
    """
    A custom formatter for file
    """
    FORMAT = "%(asctime)s {} %(name)s: %(levelname)s: %(message)s".format(socket.gethostname())
    DATEFMT = "%b %d %H:%M:%S"

    def __init__(self):
        super().__init__(fmt=self.FORMAT, datefmt=self.DATEFMT)


class DebugCustomFilter(logging.Filter):
    """
    A custom filter for debug message
    """
    def filter(self, record):
        from .config import core, report
        if record.levelname == "DEBUG":
            return core.debug or int(report.verbosity) >= 1
        if record.levelname == "DEBUG2":
            return int(report.verbosity) > 1
        else:
            return True


LOGGING_CFG = {
    "version": 1,
    "disable_existing_loggers": "False",
    "formatters": {
        "console_report": {
            "()": ConsoleReportFormatter
        },
        "console": {
            "()": ConsoleCustomFormatter
        },
        "file": {
            "()": FileCustomFormatter
        }
    },
    "filters": {
        "filter": {
            "()": DebugCustomFilter
        },
    },
    "handlers": {
        'null': {
            'class': 'logging.NullHandler'
        },
        "console_report": {
            "()": ConsoleCustomHandler,
            "formatter": "console_report",
            "filters": ["filter"]
        },
        "console": {
            "()": ConsoleCustomHandler,
            "formatter": "console",
            "filters": ["filter"]
        },
        "buffer": {
            "class": "logging.handlers.MemoryHandler",
            "capacity": 1024*100,
            "flushLevel": logging.CRITICAL,
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": CRMSH_LOG_FILE,
            "formatter": "file",
            "filters": ["filter"],
            "maxBytes": 1*1024*1024,
            "backupCount": 10
        }
    },
    "loggers": {
        "crmsh": {
            "handlers": ["null", "file", "console", "buffer"],
            "level": "DEBUG"
        },
        "crmsh.crash_test": {
            "handlers": ["null", "file", "console"],
            "propagate": False,
            "level": "DEBUG"
        },
        "crmsh.report": {
            "handlers": ["null", "file", "console_report"],
            "propagate": False,
            "level": "DEBUG"
        }
    }
}


class LoggerUtils(object):
    """
    A class to keep/update some attributes related with logger
    Also has methods related with handler and formatter
    And a set of wrapped log message for specific scenarios
    """
    def __init__(self, logger):
        """
        Init function
        """
        self.logger = logger
        # used in regression test
        self.lineno = 0
        self.__save_lineno = 0

    def set_debug2_level(self):
        """
        Create DEBUG2 level for verbosity
        """
        logging.DEBUG2 = logging.DEBUG + 5
        logging.addLevelName(logging.DEBUG2, "DEBUG2")
        self.logger.debug2 = lambda msg, *args: self.logger._log(logging.DEBUG2, msg, args)

    def get_handler(self, _type):
        """
        Get logger specific handler
        """
        for h in self.logger.handlers:
            if getattr(h, '_name') == _type:
                return h
        else:
            raise ValueError("Failed to find \"\" handler in logger \"\"".format(_type, self.logger.name))

    def disable_info_in_console(self):
        """
        Set log level as warning in console
        """
        console_handler = self.get_handler("console")
        console_handler.setLevel(logging.WARNING)

    def set_console_formatter(self, lineno):
        """
        Pass line number to ConsoleCustomFormatter
        """
        console_handler = self.get_handler("console")
        console_handler.setFormatter(ConsoleCustomFormatter(lineno=lineno))

    def reset_lineno(self, to=0):
        """
        Reset line number
        """
        self.lineno = to
        self.set_console_formatter(to)

    def incr_lineno(self):
        """
        Increase line number
        """
        self.lineno += 1
        self.set_console_formatter(self.lineno)

    @contextmanager
    def suppress_new_line(self):
        """
        Supress new line in console
        """
        console_handler = self.get_handler("console")
        try:
            console_handler.terminator = ""
            yield
        finally:
            sys.stdout.flush()
            console_handler.terminator = "\n"

    @contextmanager
    def raw_msg(self):
        """
        Only print raw message, without levelname
        """
        console_handler = self.get_handler("console")
        try:
            console_handler.setFormatter(ConsoleCustomFormatter(raw_msg=True))
            yield
        finally:
            console_handler.setFormatter(ConsoleCustomFormatter())

    @contextmanager
    def only_file(self):
        """
        Only log to file in bootstrap logger
        """
        console_handler = self.get_handler("console")
        try:
            self.logger.removeHandler(console_handler)
            yield
        finally:
            self.logger.addHandler(console_handler)

    def log_only_to_file(self, msg, level=logging.INFO):
        with self.only_file():
            self.logger.log(level, msg)

    @contextmanager
    def buffer(self):
        """
        Keep log messages in memory and finally show them in console
        """
        console_handler = self.get_handler("console")
        buffer_handler = self.get_handler("buffer")
        try:
            # remove console handler temporarily
            self.logger.removeHandler(console_handler)
            buffer_handler.buffer.clear()
            # set the target of buffer handler as console
            buffer_handler.setTarget(console_handler)
            yield
        finally:
            empty = not buffer_handler.buffer
            # close the buffer handler(flush to console handler)
            buffer_handler.close()
            # add console handler back
            self.logger.addHandler(console_handler)
            if not empty and not options.batch:
                try:
                    input("Press enter to continue... ")
                except EOFError:
                    pass

    @contextmanager
    def line_number(self):
        """
        Mark the line number in the log record
        """
        try:
            self.__save_lineno = self.lineno
            self.reset_lineno()
            yield
        finally:
            self.reset_lineno(self.__save_lineno)

    def status_done(self):
        """
        Log info message "done" in console
        """
        with self.raw_msg():
            self.logger.info("done")

    @contextmanager
    def status_long(self, msg):
        """
        To wait and mark something finished, start with msg, end of done
        """
        with self.suppress_new_line():
            self.logger.info("%s...", msg)
        try:
            yield
        except:
            print("")
            raise
        else:
            self.status_done()

    def wait_input(self, prompt_string, default=""):
        """
        Wrap input function with recording prompt string and input result
        """
        with self.suppress_new_line():
            self.logger.info(prompt_string)
        value = input()
        if not value:
            value = default
            print()
        with self.only_file():
            self.logger.info("input result: %s", value)
        return value

    def confirm(self, msg):
        """
        To ask question
        Return True when input y
        Record question and answer by wait_input
        """
        while True:
            ans = self.wait_input("{} (y/n)? ".format(msg.strip("? ")))
            if ans:
                return ans.lower() == "y"

    def syntax_err(self, s, token='', context='', msg=''):
        err = "syntax"
        if context:
            err += " in {}".format(context)
        if msg:
            err += ": {}".format(msg)
        if isinstance(s, str):
            err += " parsing '{}'".format(s)
        elif token:
            err += " near <{}> parsing '{}'".format(token, ' '.join(s))
        else:
            err += " parsing '{}'".format(' '.join(s))
        self.logger.error(err)

    def no_prog_err(self, name):
        self.logger.error("%s not available, check your installation", name)

    def unsupported_err(self, name):
        self.logger.error("%s is not supported", name)

    def missing_obj_err(self, node):
        self.logger.error("object %s:%s missing (shouldn't have happened)", node.tag, node.get("id"))

    def constraint_norefobj_err(self, constraint_id, obj_id):
        self.logger.error("constraint %s references a resource %s which doesn't exist", constraint_id, obj_id)

    def no_object_err(self, name):
        self.logger.error("object %s does not exist", name)

    def invalid_id_err(self, obj_id):
        self.logger.error("%s: invalid object id", obj_id)

    def id_used_err(self, node_id):
        self.logger.error("%s: id is already in use", node_id)

    def bad_usage(self, cmd, args, msg=None):
        if not msg:
            self.logger.error("Bad usage: '%s %s'", cmd, args)
        else:
            self.logger.error("Bad usage: %s, command: '%s %s'", msg, cmd, args)

    def empty_cib_err(self):
        self.logger.error("No CIB!")

    def text_xml_parse_err(self, msg, s):
        self.logger.error(msg)
        self.logger.info("offending string: %s", s)

    def cib_ver_unsupported_err(self, validator, rel):
        self.logger.error("Unsupported CIB: validator '%s', release '%s'", validator, rel)
        self.logger.error("To upgrade an old (<1.0) schema, use the upgrade command.")

    def update_err(self, obj_id, cibadm_opt, xml, rc):
        CIB_PERMISSION_DENIED_CODE = 54
        task_table = {"-U": "update", "-D": "delete", "-P": "patch"}
        task = task_table.get(cibadmin_opt, "replace")
        self.logger.error("could not %s %s (rc=%d)", task, obj_id, int(rc))
        if int(rc) == CIB_PERMISSION_DENIED_CODE:
            self.logger.info("Permission denied.")
        elif task == "patch":
            self.logger.info("offending xml diff: %s", xml)
        else:
            self.logger.info("offending xml: %s", xml)


def setup_directory_for_logfile():
    """
    Create log file's parent directory
    """
    _dir = os.path.dirname(CRMSH_LOG_FILE)
    os.makedirs(_dir, exist_ok=True)


def setup_logging(only_help=False):
    """
    Setup log directory and loadding logging config dict
    """
    # To avoid the potential "permission denied" error under other users (boo#1192754)
    if only_help:
        LOGGING_CFG["handlers"]["file"] = {'class': 'logging.NullHandler'}
    else:
        setup_directory_for_logfile()
    logging.config.dictConfig(LOGGING_CFG)
    if os.path.exists(CRMSH_LOG_FILE):
        shutil.chown(CRMSH_LOG_FILE, constants.HA_USER, constants.HA_GROUP)


def setup_logger(name):
    """
    Get the logger
    name could be any module name
    should assign parent's handlers for inherit
    """
    logger = logging.getLogger(name)
    logger.handlers = logger.parent.handlers
    logger.propagate = False
    return logger


def setup_report_logger(name):
    """
    Get the logger for crm report
    """
    logger = setup_logger(name)
    logger_utils = LoggerUtils(logger)
    logger_utils.set_debug2_level()
    return logger