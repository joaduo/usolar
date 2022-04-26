import gc
import utime


MEM_FREE_THRESHOLD=20000
CRITICAL = 50
FATAL = CRITICAL
ERROR = 40
WARNING = 30
WARN = WARNING
IMPORTANT = 25
INFO = 20
DEBUG = 10
NOTSET = 0

LOG_LEVEL = INFO


LOG_HISTORY_SIZE = 20
LOG_HISTORY_LEVEL = IMPORTANT

def debug(msg, *args, **kwargs):
    print_log(DEBUG, 'DEBUG:{}'.format(msg), *args, **kwargs)
def error(msg, *args, **kwargs):
    print_log(ERROR, 'ERROR:{}'.format(msg), *args, **kwargs)
def warning(msg, *args, **kwargs):
    print_log(WARNING, 'WARNING:{}'.format(msg), *args, **kwargs)
def important(msg, *args, **kwargs):
    print_log(INFO, 'INFO_HISTORY:{}'.format(msg), *args, **kwargs)
def info(msg, *args, **kwargs):
    print_log(INFO, 'INFO:{}'.format(msg), *args, **kwargs)


log_history = []
def print_log(level, msg, *args, **kwargs):
    if args or kwargs:
        msg = msg.format(*args, **kwargs)
    msg = '{}:{}'.format(utime.time(), msg)
    if LOG_LEVEL <= level:
        print(msg)
    if LOG_HISTORY_LEVEL <= level:
        log_history.append(msg)
        purge_history()


def purge_history():
    # We allow a gap of 10
    if len(log_history) >= LOG_HISTORY_SIZE + 10:
        log_history[:10] = []


def garbage_collect(threshold=MEM_FREE_THRESHOLD):
    orig_free = gc.mem_free()
    if orig_free < threshold:
        gc.collect()
        now_free=gc.mem_free()
        debug('GC: was={orig_free}, now={now_free}',
              orig_free=orig_free, now_free=now_free)
        return now_free
    return orig_free

