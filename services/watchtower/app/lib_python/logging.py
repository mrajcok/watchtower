import logging, os, shlex, sys, traceback
from . import config

PID = os.getpid()

class CustomLogFormatter(logging.Formatter):
    'adds level, pid, source, and optionally the traceback'
    def format(self, record):
        # Format the base log message
        log_msg = (f'[{PID}] {record.levelname} {record.filename}:{record.lineno} {record.msg}')
                  #f'{record.filename}:{record.funcName}:{record.lineno} {record.msg}')  
        if record.exc_info:
            # format the traceback and append it to the log message
            tb = self.formatException(record.exc_info).replace("\n", " | ").replace('"',"'")
            # flatten traceback for single-line logs
            log_msg += f' traceback="{tb}"'
        return log_msg

class CustomLogger:
    def __init__(self, name):
        self.logger    = logging.getLogger(name)
        self.log_level = config.get('log_level')
        self.setLevel()
        # It does not seem possible to set the priority of the log message when using
        # the docker journald logging driver. The best we can do is use two different
        # handlers. Logs sent to stdout get PRIORITY=6 (INFO) and logs sent to stderr
        # get PRIORITY=3 (ERROR).
        # handler for DEBUG to WARN logs
        stdout_handler = logging.StreamHandler(stream=sys.stdout)
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
        stdout_handler.setFormatter(CustomLogFormatter(datefmt='%Y-%m-%dT%H:%M:%S.%f'))
        self.logger.addHandler(stdout_handler)
        # handler for ERROR and CRITICAL logs
        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setLevel(logging.ERROR)
        stderr_handler.addFilter(lambda record: record.levelno >= logging.ERROR)
        stderr_handler.setFormatter(CustomLogFormatter(datefmt='%Y-%m-%dT%H:%M:%S.%f'))
        self.logger.addHandler(stderr_handler)

    def setLevel(self):
        log_level = config.get('log_level')
        match log_level:
            case 'DEBUG':    level = logging.DEBUG
            case 'INFO':     level = logging.INFO
            case 'WARN':     level = logging.WARN
            case 'ERROR':    level = logging.ERROR
            case 'CRITICAL': level = logging.CRITICAL
            case _:          level = logging.INFO
        self.logger.setLevel(level)
        if log_level != self.log_level:
            self.info('log-level', f'changed log level from {self.log_level} to {log_level}')
            self.log_level = log_level

    def _log(self, level, tag, msg, exc_info=None, **kv_pairs):
        ''' - replaces any double quotes in the message with single quotes
            - adds the tag and message to the log message
            - adds any key-value pairs to the log message, double-quoting
              any values that contain spaces'''
        log_msg = f'tag={tag} msg="{msg.replace('"', "'")}"'
        if kv_pairs:
            log_msg += ' ' + ' '.join(
                f'{key}={value}' if isinstance(value, (int, float)) or ' ' not in str(value)
                else f'{key}="{value.replace('"', "'")}"'
                for key, value in kv_pairs.items()
            )
        # use stacklevel=3 to adjust for the custom logger
        if exc_info:
            self.logger.log(level, log_msg, exc_info=True, stacklevel=3)
        else:
            self.logger.log(level, log_msg, stacklevel=3)

    def info(self, tag, msg, **kv_pairs):
        self._log(logging.INFO, tag, msg, **kv_pairs)

    def error(self, tag, msg, **kv_pairs):
        self._log(logging.ERROR, tag, msg, **kv_pairs)

    def warning(self, tag, msg, **kv_pairs):
        self._log(logging.WARNING, tag, msg, **kv_pairs)

    def debug(self, tag, msg, **kv_pairs):
        self._log(logging.DEBUG, tag, msg, **kv_pairs)

    def exception(self, tag, msg, **kv_pairs):
        self._log(logging.ERROR, tag, msg, exc_info=True, **kv_pairs)
        #self.logger.exception(msg)  # this would add a traceback to the log message

def configure_logging():
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('aiosqlite')     .setLevel(logging.WARNING)

log = CustomLogger('watchtower')

def parse_kv_pairs(kv_string):
    '''parses a string of key-value pairs (e.g., 'k1=v1 k2="another value') into a dict'''
    kv_pairs = {}
    for pair in shlex.split(kv_string):  # shlex handles quoted values
        if '=' in pair:
            key, value = pair.split('=', 1)
            kv_pairs[key] = value
        else:
            log.debug('parse-err', f'no "=" in {pair=}')
    return kv_pairs
