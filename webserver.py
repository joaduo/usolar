import uasyncio
import ujson
import utime
import sys
import log


CONN_TIMEOUT=10
STATUS_CODES = {
    200:'OK',
    302:'FOUND',
    404:'NOT FOUND',
    403:'FORBIDDEN',
    401:'UNAUTHORIZED',
    500:'SERVER ERROR'}
POST = 'POST'
GET = 'GET'
PUT = 'PUT'
PATCH = 'PATCH'
DELETE = 'DELETE'
EXTRA_HEADERS = {'Access-Control-Allow-Origin': '*'}
CHUNK_SIZE = 2048


def web_page(msg):
    yield '<html><body><p>'
    yield msg
    yield '</p></body></html>'


def response(status, content_type, payload, extra_headers=EXTRA_HEADERS):
    yield 'HTTP/1.1 {} {}\n'.format(status, STATUS_CODES[status])
    yield 'Content-Type: {}\n'.format(content_type)
    for k,v in extra_headers.items():
        yield k
        yield ': '
        yield v
        yield '\n'
    yield 'Connection: close\n\n'
    yield payload


def redirect(location, status=302):
    yield 'HTTP/1.1 {} {}\n'.format(status, STATUS_CODES[status])
    yield 'Location: {}\n'.format(location)


class UnauthorizedError(Exception):
    pass


class StopWebServer(Exception):
    pass


def extract_json(payload, auth_token):
    log.garbage_collect()
    msg = ujson.loads(payload[payload.rfind(b'\r\n\r\n')+4:])
    if msg.get('auth_token') != auth_token:
        raise UnauthorizedError('Unauthorized. Send {"auth_token":"<secret>", "payload": ...}')
    return msg['payload']


def jsondumps(o, depth=1):
    # Memory efficient Json String generator
    if depth and isinstance(o, dict):
        for s in _jsondumps_dict(o, depth):
            yield s
    elif depth and isinstance(o, (list, tuple, set)):
        for s in _jsondumps_iter(o, depth):
            yield s
    else:
        yield ujson.dumps(o)


def _jsondumps_iter(o, depth=1):
    depth -= 1
    yield '['
    count = 0
    lgth = len(o)
    for v in o:
        if depth:
            for s in jsondumps(v, depth):
                yield s
        else:
            yield ujson.dumps(v)
        count += 1
        if lgth != count:
            yield ' ,'
    yield ']'


def _jsondumps_dict(d, depth=1):
    depth -= 1
    yield '{'
    count = 0
    lgth = len(d)
    for k,v in d.items():
        yield ujson.dumps(k)
        yield ' : '
        if depth:
            for s in jsondumps(v, depth):
                yield s
        else:
            yield ujson.dumps(v)
        count += 1
        if lgth != count:
            yield ' ,'
    yield '}'

def serve_file(path, replacements=None):
    if replacements:
        return yield_lines(path, replacements)
    return yield_chunks(path)


def yield_chunks(path):
    with open(path) as fp:
        chunk = fp.read(CHUNK_SIZE)
        while chunk:
            yield chunk
            log.garbage_collect()
            chunk = fp.read(CHUNK_SIZE)


def yield_lines(path, replacements):
    with open(path) as fp:
        chunk = fp.readline()
        size = 0
        while chunk:
            for k,v in replacements.items():
                chunk = chunk.replace(k,v)
            yield chunk
            size += len(chunk)
            if size // CHUNK_SIZE:
                log.garbage_collect()
                size = 0
            chunk = fp.readline()


def urldecode_plus(s):
    s = s.replace('+', ' ')
    arr = s.split('%')
    res = arr[0]
    for it in arr[1:]:
        if len(it) >= 2:
            res += chr(int(it[:2], 16)) + it[2:]
        elif len(it) == 0:
            res += '%'
        else:
            res += it
    return res


def parse_query_string(s):
    s = s.strip()
    res = {}
    if not s:
        return res
    pairs = s.split('&')
    for p in pairs:
        vals = [urldecode_plus(x) for x in p.split('=', 1)]
        if len(vals) == 1:
            res[vals[0]] = ''
        else:
            res[vals[0]] = vals[1]
    return res


def file_exists(path):
    try:
        with open(path):
            pass
        return True
    except:
        return False


_endpoints = {}
class Server:

    class _endpoint_decorator:
        # Base class to later do @app.json() or @app.html() decorations
        def __init__(self, path=None,
                           response_builder=None,
                           extra_headers=EXTRA_HEADERS,
                           stream=False,
                           is_async=False,
                           **options):
            self.path = path
            self.options = dict(extra_headers=extra_headers,
                                response_builder=response_builder,
                                stream=stream,
                                is_async=is_async,
                                endpoint_type=self.__class__,
                                content_type=self.content_type,
                                **options
                                )
        def __call__(self, method):
            path = self.path or '/' + method.__name__
            _endpoints[path] = dict(method=method, options=self.options)
            return method
    class json(_endpoint_decorator):
        content_type = 'application/json'
        def __init__(self, response_builder=None,
                           extra_headers=EXTRA_HEADERS,
                           stream=False,
                           is_async=False,
                           auto_json=True,
                           auto_json_depth=0):
            super().__init__(response_builder=response_builder,
                             extra_headers=extra_headers,
                             stream=stream,
                             is_async=is_async,
                             auto_json=auto_json,
                             auto_json_depth=auto_json_depth,
                             )
    class html(_endpoint_decorator):
        content_type = 'text/html'
    class plain(_endpoint_decorator):
        content_type = 'text/plain'

    def _default_method(self, v,req,**params):
        return 'Not Found\n{}\n{}\n{}'.format(v, req, params)

    static_path = None
    static_files_replacements = {}

    def __init__(self,
                 host='0.0.0.0',
                 port=80,
                 backlog=5,
                 timeout=CONN_TIMEOUT,
                 auth_token='',
                 static_path=None,
                 static_files_replacements=None,
                 pre_request_hook=None
                 ):
        self.host = host
        self.port = port
        self.backlog = backlog
        self.timeout = timeout
        self.auth_token = auth_token
        self.static_path = static_path
        self.static_files_replacements = static_files_replacements
        self.pre_request_hook = pre_request_hook
        self.default_endpoint = dict(method=self._default_method,
                                     options=dict(
                                         endpoint_type='default',
                                         content_type='text/plain',
                                         extra_headers=EXTRA_HEADERS,
                                         response_builder=response,
                                         status=404,
                                     ))
    async def run(self):
        log.debug('Opening address={host} port={port}.', host=self.host, port=self.port)
        self.conn_id = 0 #connections ids
        self.server = await uasyncio.start_server(self.accept_conn, self.host, self.port, self.backlog)
    async def accept_conn(self, sreader, swriter):
        self.conn_id += 1
        conn_id = self.conn_id
        log.debug('Accepting conn_id={conn_id}', conn_id=conn_id)
        log.garbage_collect()
        try:
            verb, path, query_string = await self.read_request_line(sreader, self.timeout)
            payload = await uasyncio.wait_for(sreader.read(-1), self.timeout)
            log.debug('request={request!r}, conn_id={conn_id}', request=path, conn_id=conn_id)
            try:
                if self.static_path and path.startswith(self.static_path) and verb == GET:
                    resp = self.serve_static(path)
                else:
                    params = parse_query_string(query_string)
                    resp = await self.serve_request(verb, path, params, payload, swriter)
            except UnauthorizedError as e:
                resp = response(401, 'text/html', web_page('{} {!r}'.format(e,e)))
            await self.send_response(swriter, resp)
        except StopWebServer:
            raise
        except Exception as e:
            msg = 'Exception e={e} e={e!r} conn_id={conn_id}'.format(e=e, conn_id=conn_id)
            log.debug(msg)
            sys.print_exception(e)
            # If we already sent headers, we can't undo things here (but we accept such risk)
            await self.send_response(swriter, response(500, 'text/html', web_page(msg)))
        finally:
            await swriter.drain()
            log.debug('Disconnect conn_id={conn_id}.', conn_id=conn_id)
            swriter.close()
            await swriter.wait_closed()
            log.debug('Socket closed conn_id={conn_id}.', conn_id=conn_id)
            log.garbage_collect()
    async def close(self):
        log.debug('Closing server.')
        self.server.close()
        await self.server.wait_closed()
        log.info('Server closed.')
    def serve_static(self, path):
        if file_exists(path):
            content_type = 'text/html'
            if path.endswith('.js'):
                content_type = 'application/javascript'
            return response(200, content_type, serve_file(path, self.static_files_replacements))
        return response(404, 'text/html', web_page('404 Not Found'))
    async def read_request_line(self, sreader, timeout=CONN_TIMEOUT):
        while True:
            rl = await uasyncio.wait_for(sreader.readline(), timeout)
            # skip empty lines
            if rl == b'\r\n' or rl == b'\n':
                continue
            break
        rl_frags = rl.decode('utf8').split()
        if len(rl_frags) != 3:
            raise LookupError()
        verb = rl_frags[0]
        url_frags = rl_frags[1].split('?', 1)
        path = url_frags[0]
        query_string = ''
        if len(url_frags) > 1:
            query_string = url_frags[1]
        return verb, path, query_string
    async def serve_request(self, verb, path, params, req_payload, swriter):
        if self.pre_request_hook:
            self.pre_request_hook()
        endpoint = _endpoints.get(path, self.default_endpoint)
        options = endpoint['options']
        if verb == POST and options.get('auto_json'):
            req_payload = self.json_load(req_payload)
        if options.get('stream'):
            resp_payload = endpoint['method'](verb, req_payload, swriter, **params)
        else:
            resp_payload = endpoint['method'](verb, req_payload, **params)
        if options.get('is_async'):
            resp_payload = await resp_payload
        if options.get('auto_json'):
            resp_payload = self.json_dump(resp_payload, options.get('auto_json_depth', 0))
        response_builder = options['response_builder'] or response
        return response_builder(options.get('status', 200), options['content_type'], resp_payload, extra_headers=options['extra_headers'])
    async def send_response(self, swriter, resp):
        if isinstance(resp, (str, bytes)):
            if resp:
                swriter.write(resp)
                return len(resp)
            return 0
        #elif iscoroutine(resp): # Disabled. We can't distiguish a generator from a coroutine
        #    return await self.send_response(swriter, await resp)
        else:
            count = 0
            for l in resp:
                count += await self.send_response(swriter, l)
                if count // CHUNK_SIZE:
                    await swriter.drain()
                    count = 0
            return count
    def json_load(self, payload):
        return extract_json(payload, self.auth_token)
    def json_dump(self, obj, depth=1):
        return jsondumps(obj, depth)



def main():
    app = Server(static_path='/static/')
    log.LOG_LEVEL = log.DEBUG
    log.garbage_collect()
    try:
        uasyncio.run(app.run())
        uasyncio.get_event_loop().run_forever()
    finally:
        uasyncio.run(app.close())
        _ = uasyncio.new_event_loop()


if __name__ == '__main__':
    main()

