import gc


MEM_FREE_THRESHOLD=20000
CRITICAL = 50
FATAL = CRITICAL
ERROR = 40
WARNING = 30
WARN = WARNING
INFO = 20
DEBUG = 10
NOTSET = 0

LOG_LEVEL = INFO

def debug(msg, *args, **kwargs):
    if LOG_LEVEL <= DEBUG:
        print_log('DEBUG:{}'.format(msg), *args, **kwargs)
def error(msg, *args, **kwargs):
    if LOG_LEVEL <= ERROR:
        print_log('ERROR:{}'.format(msg), *args, **kwargs)
def info(msg, *args, **kwargs):
    if LOG_LEVEL <= INFO:
        print_log('INFO:{}'.format(msg), *args, **kwargs)


def print_log(msg, *args, **kwargs):
    if args:
        msg = msg % args
    if kwargs:
        msg = msg.format(**kwargs)
    print(msg)


def garbage_collect():
    orig_free = gc.mem_free()
    if orig_free < MEM_FREE_THRESHOLD:
        gc.collect()
        info('GC: was={orig_free}, now={now_free}',
              orig_free=orig_free, now_free=gc.mem_free())

