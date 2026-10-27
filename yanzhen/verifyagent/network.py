"""Pin TCP destinations without changing HTTP URLs, cookies, Host or TLS SNI."""
from __future__ import annotations

import ssl
from contextlib import contextmanager

import httpcore
import httpx


@contextmanager
def network_errors():
    try:
        yield
    except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as exc:
        kind = getattr(httpx, type(exc).__name__, httpx.TransportError)
        raise kind(str(exc)) from exc


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, hostname, address):
        self.hostname, self.address = hostname, address
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.hostname:
            raise httpcore.ConnectError('Connection escaped its pinned hostname')
        return await self.backend.connect_tcp(self.address, port, timeout=timeout,
                                              local_address=local_address, socket_options=socket_options)


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        with network_errors():
            async for chunk in self.stream:
                yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, hostname, address, *, ssl_context=None):
        self.pool = httpcore.AsyncConnectionPool(network_backend=PinnedBackend(hostname, address),
                                                ssl_context=ssl_context or ssl.create_default_context(), retries=0)

    async def handle_async_request(self, request):
        core_request = httpcore.Request(method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                             port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        with network_errors():
            response = await self.pool.handle_async_request(core_request)
        return httpx.Response(response.status, headers=response.headers,
                              stream=ResponseStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()
