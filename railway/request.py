from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Generic, Iterable, Literal, NoReturn, TypeVar, Union, Any, Optional, Type, NamedTuple
from abc import ABC, abstractmethod
import datetime
import base64
import hashlib
import asyncio

from .errors import PartialRead
from .url import URL
from .headers import Headers
from .response import Response
from .cookies import Cookie, CookieJar
from .sessions import CookieSession, AbstractSession
from .responses import HTTPException, Redirection, SwitchingProtocols, redirects, responses
from .response import StreamResponse
from .formdata import FormData
from .streams import StreamReader, StreamWriter
from .types import ResponseBody, ResponseStatus, RouteResponse, StrURL, Address
from .utils import to_url, GUID, CLRF, parse_headers, loads, dumps

if TYPE_CHECKING:
    from .objects import Route, WebSocketRoute
    from .workers import Worker
    from .app import Application

    FlashMessageCategories = Literal['message', 'success', 'error', 'warning', 'info']
    SessionT = TypeVar('SessionT', bound=AbstractSession)

AppT = TypeVar('AppT', bound='Application', covariant=True)

__all__ = (
    'Request',
    'HTTPConnection'
)

class HTTPConnection(ABC):
    _body: bytes
    headers: Headers

    async def stream(self, *, timeout: Optional[float] = None) -> AsyncIterator[bytes]:
        """
        The body of the request as a stream.

        Parameters
        ----------
        timeout: Optional[:class:`float`]
            The timeout to use.
        """
        if not self.headers.content_length:
            yield b''
            return

        reader = self.get_reader()
        while not reader.at_eof():
            try:
                chunk = await reader.read(65536, timeout=timeout)
            except asyncio.TimeoutError:
                continue
            except PartialRead as e:
                chunk = e.partial
            
            yield chunk

    async def read(self, *, timeout: Optional[float] = None) -> bytes:
        """
        Reads the body of the request.

        Parameters
        ----------
        timeout: Optional[:class:`float`]
            The timeout to use.

        Returns
        -------
        :class:`bytes`
            The body of the request as bytes.
        """
        reader = self.get_reader()
        if not reader.at_eof():
            async for chunk in self.stream():
                self._body += chunk
            
        return self._body

    async def text(self, *, encoding: Optional[str] = None) -> str:
        """
        The text of the request.

        Parameters
        ----------
        encoding: Optional[:class:`str`]
            The encoding to use.
        """
        if encoding is None:
            encoding = self.headers.charset if self.headers.charset else 'utf-8'

        body = await self.read()
        return body.decode(encoding=encoding)

    async def json(self, *, check_content_type: bool = False, encoding: Optional[str] = None) -> Any:
        """
        The JSON body of the request.

        Parameters
        ----------
        check_content_type: :class:`bool`
            Whether to check if the content type is application/json or not.
        encoding: Optional[:class:`str`]
            The encoding to use.
        """
        if check_content_type:
            ret = f'Content-Type must be application/json, got {self.headers.content_type!r}'
            assert self.headers.content_type == 'application/json', ret

        text = await self.text(encoding=encoding)
        return loads(text)

    @abstractmethod
    def get_reader(self) -> StreamReader:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_closed(self) -> bool:
        raise NotImplementedError

class Request(Generic[AppT], HTTPConnection):
    """
    A request that is sent to the server.

    Attributes
    ----------
    method: :class:`str`
        The HTTP method.
    version: :class:`str`
        The HTTP version.
    headers: :class:`dict`
        The HTTP headers.
    created_at: :class:`datetime.datetime`
        The time the request was created.
    route: :class:`~railway.objects.Route`
        The route that the request was sent to.
    worker: 
        The worker that the request was sent to.
    """
    def __init__(
        self,
        method: str,
        url: str,
        headers: Headers,
        version: str,
        app: AppT,
        reader: StreamReader,
        writer: StreamWriter,
        worker: Worker,
        created_at: datetime.datetime
    ):
        self._encoding = "utf-8"
        self._app = app
        self._reader = reader
        self._writer = writer
        self._url = url
        self._body = b''
        self.version = version
        self.method = method
        self.worker = worker
        self.headers = headers
        self.route: Optional[Union[Route, WebSocketRoute]] = None
        self.created_at: datetime.datetime = created_at

        self._closed = False

    async def send(
        self,
        response: RouteResponse,
        *,
        convert: bool = True,
    ) -> None:
        """
        Sends a response to the client.

        Parameters
        ----------
        response: 
            The response to send.

        Raises
        ------
        ValueError: If the response is not parsable.
        """
        if convert:
            response = await self.app.parse_response(response)
        else:
            if not isinstance(response, Response):
                raise ValueError('When convert is passed in as False, response must be a Response object')

        data = await response.prepare()
        await self.writer.write(data, drain=True)

        if isinstance(response, StreamResponse):
            async for chunk in response:
                await self.writer.write(chunk, drain=True)

    async def close(self):
        """
        Closes the connection.
        """
        if not self.is_closed():
            self.writer.close()
            await self.writer.wait_closed()

    async def handshake(
        self, 
        *, 
        extensions: Optional[Iterable[str]] = None, 
        subprotocols: Optional[Iterable[str]] = None
    ) -> None:
        """
        Performs a websocket handshake.

        Parameters
        ----------
        extensions: Optional[Iterable[str]]
            The extensions to use.
        subprotocols: Optional[Iterable[str]]
            The subprotocols to use.
        """
        key = self.parse_websocket_key()
        response = SwitchingProtocols()

        response.add_header(key='Upgrade', value='websocket')
        response.add_header(key='Connection', value='Upgrade')
        response.add_header(key='Sec-WebSocket-Accept', value=key)

        if extensions is not None:
            response.add_header(key='Sec-WebSocket-Extensions', value=', '.join(extensions))
        
        if subprotocols is not None:
            response.add_header(key='Sec-WebSocket-Protocol', value=', '.join(subprotocols))

        data = await response.prepare()
        await self.writer.write(data, drain=True)

    def is_closed(self) -> bool:
        """
        True if the connection is closed.
        """
        return self._closed

    def is_websocket(self) -> bool:
        """
        True if the request is a websocket request.
        """
        if self.method != 'GET':
            return False

        if self.version != 'HTTP/1.1':
            return False

        required = (
            'Host',
            'Upgrade',
            'Connection',
            'Sec-WebSocket-Version',
            'Sec-WebSocket-Key',
        )

        if not all([header in self.headers for header in required]):
            return False

        for header in required:
            value = self.headers[header]

            if header == 'Upgrade':
                if value.lower() != 'websocket':
                    return False
            elif header == 'Sec-WebSocket-Version':
                if value != '13':
                    return False
            elif header == 'Sec-WebSocket-Key':
                key = base64.b64decode(value)

                if not len(key) == 16:
                    return False

        return True

    def get_reader(self) -> StreamReader:
        return self._reader

    @property
    def encoding(self) -> str:
        """
        The encoding of the request.
        """
        charset = self.headers.charset
        if charset:
            return charset

        return self._encoding

    @encoding.setter
    def encoding(self, value: str):
        self._encoding = value

    @property
    def writer(self) -> StreamWriter:
        """
        The writer for the request.
        """
        return self._writer

    @property
    def app(self) -> AppT:
        """
        The application.
        """
        return self._app

    @property
    def url(self):
        """
        The URL of the request.
        """
        return URL(self._url)

    @property
    def query(self):
        """
        The query dict of the request.
        """
        return self.url.query

    @property
    def cookies(self) -> CookieJar:
        """
        The cookies of the request.
        """
        return self.headers.cookies

    @property
    def client(self) -> Address:
        """
        The address of the client.

        Returns
        -------
        :class:`collections.namedtuple`
            A named tuple with the host and port of the client.
        """
        host, port = self.writer.get_extra_info('peername')

        if 'X-Forwarded-For' in self.headers:
            host = self.headers['X-Forwarded-For']

        return Address(host, port)

    @property
    def server(self) -> Address:
        """
        The address of the server.

        Returns
        -------
        :class:`collections.namedtuple`
            A named tuple with the host and port of the client.
        """
        host, port = self.writer.get_extra_info('sockname')
        return Address(host, port)

    def get_default_session_cookie(self) -> Optional[Cookie]:
        """
        Gets the default session cookie.
        """
        cookie_session_name = self.app.settings['session_cookie_name']
        cookie = self.cookies.get(cookie_session_name)

        return cookie if cookie is not None else None

    def parse_websocket_key(self) -> str:
        """
        Parses the websocket key from the request.
        """
        if not self.is_websocket():
            raise RuntimeError('Not a websocket request')

        key: str = self.headers['Sec-WebSocket-Key']

        sha1 = hashlib.sha1((key + GUID).encode()).digest()
        return base64.b64encode(sha1).decode()

    async def form(self) -> FormData:
        """
        The form data of the request.
        """
        return await FormData.from_request(self)

    async def session(self, *, cls: Type[SessionT] = CookieSession) -> SessionT:
        """
        The session of the request.

        Parameters
        ----------
        cls: Type[SessionT]
            The class of the session.

        Returns
        -------
        SessionT
            The session.
        """
        return await cls.from_request(self)

    async def redirect(
        self,
        to: StrURL,
        *,
        status: Optional[ResponseStatus] = None,
        body: Optional[ResponseBody] = None,
        **kwargs: Any
    ) -> NoReturn:
        """
        Redirects a request to another URL.

        Parameters
        ----------
        to: Union[str, :class:`~railway.datastructures.URL`]
            The URL to redirect to.
        body: Any
            The body of the response.
        **kwargs: Any
            The keyword arguments to pass to the response.
        
        Raises
        ------
        ValueError: If ``status`` is not valid redirection status code.
        """
        status = status or 302

        url = to_url(to)
        cls: Optional[Type[Redirection]] = redirects.get(int(status)) # type: ignore

        if not cls:
            ret = f'{status} is not a valid redirect status code'
            raise ValueError(ret)

        response = cls(location=url, body=body, **kwargs)
        raise response

    async def abort(
        self,
        status: ResponseStatus,
        *,
        message: Optional[ResponseBody] = None,
        **kwargs: Any,
    ) -> NoReturn:
        """
        Aborts a request with a response.

        Parameters
        ----------
        status: Union[:class:`int`, :class:`~.HTTPStatus`]
            The status code of the response.
        message: Any
            The body of the response.
        **kwargs: Any
            The keyword arguments to pass to the response.

        Raises
        ------
        ValueError: If ``status`` is not valid response status code.
        """
        if status < 400:
            raise ValueError('status must be >= 400')

        cls: Type[HTTPException] = responses.get(int(status)) # type: ignore
        
        response = cls(reason=message, **kwargs)
        raise response

    async def render(self, template: str, *args: Any, **kwargs: Any):
        """
        Renders a template.
        A shortcut for :meth:`~railway.Application.render`.

        Parameters
        ----------
        template: :class:`str`
            The template to render.
        *args: Any
            The positional arguments to pass to the template.
        **kwargs: Any
            The keyword arguments to pass to the template.
        """
        kwargs.setdefault('request', self)
        return await self.app.render(template, *args, **kwargs)

    @classmethod
    async def parse(
        cls, 
        status_line: bytes, 
        reader: StreamReader,
        writer: StreamWriter,
        worker: Worker, 
        created_at: datetime.datetime
    ) -> Request[Application]:
        method, path, version = status_line.decode().split(' ')

        hdrs = await reader.readuntil(CLRF * 2)
        headers = Headers(parse_headers(hdrs))

        return cls(
            method=method,
            url=path,
            version=version,
            headers=headers,
            app=worker.app,
            reader=reader,
            writer=writer,
            worker=worker,
            created_at=created_at
        )

    def __repr__(self) -> str:
        return '<Request url={0.url.path!r} method={0.method!r} version={0.version!r}>'.format(self)
