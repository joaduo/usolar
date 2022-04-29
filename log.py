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
    print_log(DEBUG, msg, *args, **kwargs)
def error(msg, *args, **kwargs):
    print_log(ERROR, msg, *args, **kwargs)
def warning(msg, *args, **kwargs):
    print_log(WARNING, msg, *args, **kwargs)
def important(msg, *args, **kwargs):
    print_log(IMPORTANT, msg, *args, **kwargs)
def info(msg, *args, **kwargs):
    print_log(INFO, msg, *args, **kwargs)


web_log_history = []
web_log_frequency = {}
def print_log(level, msg, *args, **kwargs):
    if LOG_LEVEL <= level:
        if args or kwargs:
            print(msg.format(*args, **kwargs))
    if WEB_LOG_LEVEL <= level:
        time = utime.time()
        web_log_history.append((time,level,msg,args,kwargs))
        if msg not in web_log_frequency:
            web_log_frequency[msg] = dict(count=0)
        web_log_frequency[msg]['count'] += 1
        web_log_frequency[msg]['last_seen'] = time
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

