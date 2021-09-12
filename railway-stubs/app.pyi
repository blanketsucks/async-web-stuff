from .errors import *
import asyncio
import pathlib
import socket as _socket
import ssl
from ._types import CoroFunc
from .file import File
from .injectables import Injectable, InjectableMeta
from .objects import Listener, Middleware, PartialRoute, Route, WebsocketRoute
from .request import Request
from .resources import Resource
from .response import Response
from .router import Router
from .settings import Settings
from .views import HTTPView
from .datastructures import URL
from .workers import Worker
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

class Application(Injectable, metaclass=InjectableMeta):
    settings: Settings = ...
    host: str = ...
    port: int = ...
    url_prefix: str = ...
    router: Router = ...
    ssl_context: Optional[ssl.SSLContext] = ...
    worker_count: int = ...
    def __init__(self, host: Optional[str]=..., port: Optional[int]=..., url_prefix: Optional[str]=..., *, loop: Optional[asyncio.AbstractEventLoop]=..., settings: Optional[Settings]=..., settings_file: Optional[Union[str, pathlib.Path]]=..., load_settings_from_env: Optional[bool]=..., ipv6: bool=..., sock: Optional[socket.socket]=..., worker_count: Optional[int]=..., use_ssl: Optional[bool]=..., ssl_context: Optional[ssl.SSLContext]=...) -> None: ...
    async def __aenter__(self) -> Application: ...
    def __getitem__(self, item: str): ...
    async def parse_response(self, response: Union[str, bytes, Dict[str, Any], List[Any], Tuple[Any, Any], File, Response, Any]) -> Optional[Response]: ...
    def set_default_cookie(self, request: Request, response: Response) -> Response: ...
    @property
    def workers(self) -> List[Worker]: ...
    @property
    def views(self) -> List[HTTPView]: ...
    @property
    def socket(self) -> _socket.socket: ...
    @property
    def middlewares(self) -> List[Middleware]: ...
    @property
    def listeners(self) -> List[Listener]: ...
    @property
    def resources(self) -> List[Resource]: ...
    @property
    def loop(self) -> asyncio.AbstractEventLoop: ...
    @loop.setter
    def loop(self, value: Any) -> None: ...
    @property
    def urls(self) -> Set[URL]: ...
    @property
    def paths(self) -> Set[str]: ...
    def url_for(self, path: str, *, is_websocket: bool=..., **kwargs: Any) -> URL: ...
    def inject(self, obj: Injectable) -> Any: ...
    def eject(self, obj: Injectable) -> Any: ...
    def is_closed(self) -> bool: ...
    def is_serving(self) -> bool: ...
    def is_ipv6(self) -> bool: ...
    def is_ssl(self) -> bool: ...
    def get_worker(self, id: int) -> Optional[Worker]: ...
    def add_worker(self, worker: Union[Worker, Any]) -> Worker: ...
    def start(self) -> None: ...
    def run(self): ...
    async def close(self) -> None: ...
    def websocket(self, path: str) -> Callable[[CoroFunc], WebsocketRoute]: ...
    def route(self, path: str, method: Optional[str]=...) -> Callable[[CoroFunc], Route]: ...
    def add_route(self, route: Union[Route, WebsocketRoute, Any]) -> Union[Route, WebsocketRoute]: ...
    def add_router(self, router: Union[Router, Any]) -> Router: ...
    def get(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def put(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def post(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def delete(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def head(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def options(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def patch(self, path: str) -> Callable[[CoroFunc], Route]: ...
    def remove_route(self, route: Union[Route, WebsocketRoute]) -> Union[Route, WebsocketRoute]: ...
    def add_event_listener(self, coro: CoroFunc, name: Optional[str]=...) -> Listener: ...
    def remove_event_listener(self, listener: Listener) -> Listener: ...
    def event(self, name: Optional[str]=...) -> Callable[[CoroFunc], Listener]: ...
    def dispatch(self, name: str, *args: Any, **kwargs: Any) -> Any: ...
    def add_view(self, view: Union[HTTPView, Any]) -> HTTPView: ...
    def remove_view(self, path: str) -> Optional[HTTPView]: ...
    def get_view(self, path: str) -> Optional[HTTPView]: ...
    def view(self, path: str) -> Any: ...
    def add_resource(self, resource: Union[Resource, Any]) -> Resource: ...
    def remove_resource(self, name: str) -> Optional[Resource]: ...
    def get_resource(self, name: str) -> Optional[Resource]: ...
    def resource(self, name: str=...) -> Callable[[Type[Resource]], Resource]: ...
    def add_middleware(self, callback: CoroFunc) -> Middleware: ...
    def middleware(self, callback: CoroFunc) -> Middleware: ...
    def remove_middleware(self, middleware: Middleware) -> Middleware: ...
    async def on_error(self, route: Union[Route, PartialRoute], request: Request, worker: Worker, exception: Exception) -> Any: ...

def dualstack_ipv6(ipv4: str=..., ipv6: str=..., *, port: int=..., **kwargs: Any) -> Application: ...
