from .abc import Hooker
from .request import HTTPRequest
from .response import HTTPResponse
from .sessions import HTTPSession
from railway.websockets import ClientWebsocket as Websocket, WebSocketCloseCode
from typing import Any, Optional

class TCPHooker(Hooker):
    connected: bool = ...
    closed: bool = ...
    def __init__(self, session: HTTPSession) -> None: ...
    async def create_ssl_connection(self, host: str) -> Any: ...
    async def create_connection(self, host: str) -> Any: ...
    async def write(self, data: HTTPRequest) -> Any: ...
    async def read(self) -> bytes: ...
    async def close(self) -> None: ...

class WebsocketHooker(TCPHooker):
    websocket: Websocket = ...
    def __init__(self, session: HTTPSession) -> None: ...
    async def create_connection(self, host: str, path: str) -> Any: ...
    async def create_ssl_connection(self, host: str, path: str) -> Any: ...
    def generate_websocket_key(self): ...
    def create_websocket(self): ...
    async def handshake(self, path: str, host: str) -> Any: ...
    async def verify_handshake(self, response: HTTPResponse) -> Any: ...
    async def close(self, *, data: Optional[bytes]=..., code: Optional[WebSocketCloseCode]=...) -> None: ...