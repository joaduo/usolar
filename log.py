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


WEB_LOG_SIZE = 20
WEB_LOG_LEVEL = IMPORTANT

def debug(msg, *args, **kwargs):
    print_log(DEBUG, 'DEBUG:{}'.format(msg), *args, **kwargs)
def error(msg, *args, **kwargs):
    print_log(ERROR, 'ERROR:{}'.format(msg), *args, **kwargs)
def warning(msg, *args, **kwargs):
    print_log(WARNING, 'WARNING:{}'.format(msg), *args, **kwargs)
def important(msg, *args, **kwargs):
    print_log(IMPORTANT, 'IMPORTANT:{}'.format(msg), *args, **kwargs)
def info(msg, *args, **kwargs):
    print_log(INFO, 'INFO:{}'.format(msg), *args, **kwargs)


web_log_history = []
web_log_frequency = {}
def print_log(level, msg, *args, **kwargs):
    orig_msg = msg
    if args or kwargs:
        msg = msg.format(*args, **kwargs)
    time = utime.time()
    msg = '{}:{}'.format(utime.time(), msg)
    if LOG_LEVEL <= level:
        print(msg)
    if WEB_LOG_LEVEL <= level:
        web_log_history.append(msg)
        if orig_msg not in web_log_frequency:
            web_log_frequency[orig_msg] = dict(count=0)
        web_log_frequency[orig_msg]['count'] += 1
        web_log_frequency[orig_msg]['last_seen'] = time
        purge_history()


def purge_history():
    # We allow a gap of 10
    if len(web_log_history) >= WEB_LOG_SIZE + 10:
        web_log_history[:10] = []


def garbage_collect(threshold=MEM_FREE_THRESHOLD):
    orig_free = gc.mem_free()
    if orig_free < threshold:
        gc.collect()
        now_free=gc.mem_free()
        debug('GC: was={orig_free}, now={now_free}',
              orig_free=orig_free, now_free=now_free)
        return now_free
    return orig_free

