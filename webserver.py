import uasyncio
import ujson
import utime
import sys
import log


AUTH_TOKEN='1234'
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


def extract_json(request):
    log.garbage_collect()
    msg = ujson.loads(request[request.rfind(b'\r\n\r\n')+4:])
    if msg.get('auth_token') != AUTH_TOKEN:
        raise UnauthorizedError('Unauthorized. Send {"auth_token":"<secret>", "payload": ...}')
    return msg['payload']


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
                size = size % CHUNK_SIZE
            chunk = fp.readline()


class Server:
    static_path = None
    static_files_replacements = {}
    def __init__(self, serve_request, host='0.0.0.0', port=80, backlog=5, timeout=CONN_TIMEOUT):
        self.serve_request = serve_request
        self.host = host
        self.port = port
        self.backlog = backlog
        self.timeout = timeout
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
            request = await uasyncio.wait_for(sreader.readline(), self.timeout)
            request_trailer = await uasyncio.wait_for(sreader.read(-1), self.timeout)
            log.debug('request={request!r}, conn_id={conn_id}', request=request, conn_id=conn_id)
            verb, path = request.decode('utf8').split()[0:2]
            try:
                if self.static_path and path.startswith(self.static_path) and verb == GET:
                    resp = self.serve_static(path)
                else:
                    resp = await self.serve_request(verb, path, request_trailer)
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
    async def send_response(self, swriter, resp):
        if isinstance(resp, (str, bytes)):
            if resp:
                swriter.write(resp)
                return len(resp)
            return 0
        else:
            count = 0
            for l in resp:
                count += await self.send_response(swriter, l)
                if count // CHUNK_SIZE:
                    await swriter.drain()
                    count = count % CHUNK_SIZE
            return count
    def serve_static(self, path):
        if self.file_exists(path):
            content_type = 'text/html'
            if path.endswith('.js'):
                content_type = 'application/javascript'
            return response(200, content_type, serve_file(path, self.static_files_replacements))
        return response(404, 'text/html', web_page('404 Not Found'))
    def file_exists(self, path):
        try:
            with open(path):
                pass
            return True
        except:
            return False


def main():
    async def serve_request(verb, path, request_trailer):
        if path == '/redirect':
            return redirect('http://192.168.2.107/static/client.html')
        else:
            return response(200, 'text/html', web_page(
                '<h2>Hellow World</h2><pre>{}</pre>'.format(request_trailer.decode('utf8'))))
    server = Server(serve_request)
    server.static_path = '/static/'
    log.garbage_collect()
    try:
        uasyncio.run(server.run())
        uasyncio.get_event_loop().run_forever()
    finally:
        uasyncio.run(server.close())
        _ = uasyncio.new_event_loop()


if __name__ == '__main__':
    main()

