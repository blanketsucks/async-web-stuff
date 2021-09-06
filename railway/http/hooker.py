import os
import base64

from typing import TYPE_CHECKING, Optional

from railway.utils import find_headers
from railway.websockets import (
    ClientWebsocket as Websocket,
    WebSocketCloseCode, 
)
from railway.client import Client
from railway.response import HTTPStatus
from .request import Request
from .abc import Hooker
from .errors import HandshakeError
from .response import Response

if TYPE_CHECKING:
    from .sessions import HTTPSession

__all__ = (
    'Websocket',
    'TCPHooker',
    'WebsocketHooker'
)

class TCPHooker(Hooker):
    def __init__(self, session: 'HTTPSession') -> None:
        super().__init__(session)

    async def _create_connection(self, host: str):
        self.ensure()

        try:
            host, port = host.split(':')
        except ValueError:
            port = 80

        self._client = Client(host, int(port))
        await self._client.connect()

        self.connected = True
        return self._client
    
    async def _create_ssl_connection(self, host: str):
        self.ensure()
        context = self.create_default_ssl_context()

        try:
            host, port = host.split(':')
        except ValueError:
            port = 443

        self._client = Client(host, int(port), ssl_context=context)
        await self._client.connect()

        self.connected = True
        return self._client

    async def create_ssl_connection(self, host: str):
        client = await self._create_ssl_connection(host)
        return client

    async def create_connection(self, host: str):
        client = await self._create_connection(host)
        return client

    async def write(self, data: Request):
        await self._client.write(data.encode())

    async def read(self) -> bytes:
        if not self._client:
            return b''

        data = await self._client.receive()
        return data

    async def _read_body(self) -> bytes:
        data = await self.read()
        _, body = find_headers(data)

        return body

    async def close(self):
        await self._client.close()
        
        self.connected = False
        self.closed = True

class WebsocketHooker(TCPHooker):
    def __init__(self, session: 'HTTPSession') -> None:
        super().__init__(session)

        self._task = None

    async def create_connection(self, host: str, path: str): # type: ignore
        await super().create_connection(host)
        ws = await self.handshake(path, host)

        return ws

    async def create_ssl_connection(self, host: str, path: str): # type: ignore
        await super().create_ssl_connection(host)
        ws = await self.handshake(path, host)

        return ws

    def generate_websocket_key(self):
        return base64.b64encode(os.urandom(16))

    def create_websocket(self):
        reader = self._client._protocol.reader # type: ignore
        writer = self._client._protocol.writer # type: ignore

        if not reader or not writer:
            return

        return Websocket(reader, writer)
    
    async def handshake(self, path: str, host: str):
        key = self.generate_websocket_key().decode()
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Sec-WebSocket-Key': key,
            'Sec-WebSocket-Version': 13
        }

        request = self.build_request('GET', host, path, headers, None)
        await self.write(request)

        handshake = await self._client.receive()
        response = await self.build_response(data=handshake)

        self.websocket = self.create_websocket()
        await self.verify_handshake(response)

        return self.websocket

    async def verify_handshake(self, response: Response):
        headers = response.headers

        if response.status is not HTTPStatus.SWITCHING_PROTOCOLS:
            return await self._close(
                HandshakeError(
                    message=f"Expected status code '101', but received {response.status.value!r} instead",
                    hooker=self,
                    client=self.session
                    )
            )

        connection = headers.get('Connection')
        if connection is None or connection.lower() != 'upgrade':
            return await self._close(
                HandshakeError(
                    message=f"Expected 'Connection' header with value 'upgrade', but got {connection!r} instead",
                    hooker=self,
                    client=self.session
                )
            )

        upgrade = response.headers.get('Upgrade')
        if upgrade is None or upgrade.lower() != 'websocket':
            return await self._close(
                HandshakeError(
                    message=f"Expected 'Upgrade' header with value 'websocket', but got {upgrade!r} instead",
                    hooker=self,
                    client=self.session
                    )
            )

    async def _close(self, exc: Exception):
        await self.close()
        raise exc

    async def close(self, *, data: Optional[bytes]=None, code: Optional[WebSocketCloseCode]=None) -> None:
        if not self.websocket:
            return

        if not code:
            code = WebSocketCloseCode.NORMAL

        if not data:
            data = b''

        return await self.websocket.close(data, code)