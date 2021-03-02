
from .request import Request
from .errors import *
from .server import *
from .router import Router
from .utils import format_exception, jsonify, VALID_METHODS
from .settings import Settings
from .objects import Route, Listener, Middleware, WebsocketRoute
from .shards import Shard
from .base import Base
from .context import Context, _ContextManager
from .cache import Cache
from .views import HTTPView, WebsocketHTTPView

import inspect
import typing
import yarl
import jwt
import datetime
import asyncpg
import aiosqlite
import aioredis
import aiohttp
import asyncio
import pathlib
import importlib
import watchgod

class _RequestContextManager:
    def __init__(self, session: aiohttp.ClientSession, url: str, method: str, **kwargs) -> None:
        self.__session = session

        self.url = url
        self.method = method
        self.kwargs = kwargs

    async def __aenter__(self):
        method = self.method
        url = self.url
        kwargs = self.kwargs

        async with self.__session.request(method, url, **kwargs) as resp:
            return resp

    async def __aexit__(self, _type, value, tb):
        await self.__session.close()
        return self

__all__ = (
    'VALID_METHODS',
    'Application',
)

class Application(Base):
    """
    
    ## Listeners order

    `on_startup` -> `on_connection_made` -> `on_request` -> `on_socket_receive` -> `on_connection_lost` -> `on_shutdown`
    
    """
    def __init__(self, routes: typing.List[Route]=None,
                listeners: typing.List[Listener]=None,
                middlewares: typing.List[Middleware]=None, *,
                loop: asyncio.AbstractEventLoop=None,
                url_prefix: str=None,
                settings_file: typing.Union[str, pathlib.Path]=None,
                load_settings_from_env: bool=False,
                routes_cache_maxsize: int=64) -> None:

        self._ready = asyncio.Event()
        self._request = asyncio.Event()

        self.loop = loop or asyncio.get_event_loop()
        self.url_prefix = url_prefix

        self.settings = Settings()
        self.router = Router()
        self.cache = Cache(routes_maxsize=routes_cache_maxsize)

        if settings_file:
            self.settings.from_file(settings_file)

        if load_settings_from_env:
            self.settings.from_env_vars()

        self.shards: typing.Dict[str, Shard] = {}
        self.views: typing.List[typing.Union[HTTPView, WebsocketHTTPView]] = []
        self._websocket_tasks: typing.List[asyncio.Task] = []

        self._is_websocket: bool = False
        self.__session: aiohttp.ClientSession = None
        self._server: asyncio.AbstractServer = None
        self._database_connection = None

        super().__init__(routes=routes,
                        listeners=listeners,
                        middlewares=middlewares,
                        url_prefix=url_prefix,
                        loop=self.loop
                        )

    def __repr__(self) -> str:
        # {0.__class__.__name__} because of the subclass: RESTApplication
        return '<{0.__class__.__name__} settings={0.settings} cache={0.cache}>'.format(self)

    # Private methods

    async def _watch_for_changes(self):
        async for changes in watchgod.awatch('.', watcher_cls=watchgod.PythonWatcher):
            for change in changes:
                self.__datetime = datetime.datetime.utcnow().strftime('%Y-%m-%d | %H:%M:%S')
                print(f"[{self.__datetime}]: Detected change in {change[1]}. Reloading.")

                filepath = change[1][2:-3].replace('\\', '.')
                
                module = importlib.import_module(filepath)
                importlib.reload(module)

    def _start_tasks(self):
            for task in self._tasks:
                task.start()

    def _convert(self, func, args):
        return_args = []
        params = inspect.signature(func)

        for key, value in params.parameters.items():
            for name, match in args.items():
                if key == name:
                    try:
                        param = value.annotation(match)
                    except ValueError:
                        fut = 'Failed conversion to {0!r} for paramater {1!r}.'.format(value.annotation.__name__, key)
                        raise BadConversion(fut) from None
                    else:
                        return_args.append(param)

        return return_args

    async def _handler(self, request: Request, response_writer):
        resp = None
        try:
            args, route = self.router.resolve(request)
            self.cache.add_route(route, request)

            if len(self._middlewares) != 0:
                await asyncio.gather(*[middleware(request, route.coro) for middleware in self._middlewares])

            args = self._convert(route.coro, args)
            ctx = Context(app=self, request=request)

            if isinstance(route, Route):
                resp = await route(ctx, *args)

            if isinstance(route, WebsocketRoute):
                protocol = request.protocol
                ws = await protocol._websocket(request, route.subprotocols)

                task = self.loop.create_task(route(ctx, ws, *args))
                self._websocket_tasks.append(task)

            if isinstance(resp, Context):
                resp = resp.response

                if resp is None:
                    raise RuntimeError('A route should not return None')

            self.cache.set(context=ctx, response=resp, request=request)  
        except HTTPException as exc:
            resp = format_exception(exc)

        except Exception as exc:
            resp = format_exception(exc)
  
        self._request.set()
        response_writer(resp.as_string())

    # context managers

    def context(self):
        if not self.cache.context:
            raise RuntimeError('a Context object has not been set')
        
        return _ContextManager(self.cache.context)

    # Ready up stuff

    async def wait_until_request(self):
        await self._request.wait()

    async def wait_until_startup(self):
        await self._ready.wait()

    def is_ready(self):
        return self._ready.is_set()

    # Properties

    @property
    def shard_count(self):
        return len(self.shards)

    @property
    def running_tasks(self):
        return len([task for task in self._tasks if task.is_running])

    @property
    def sockets(self) -> typing.Tuple:
        return self._server.sockets if self._server else ()

    # Some methods. idk

    def get_database_connection(self) -> typing.Optional[typing.Union[asyncpg.pool.Pool, aioredis.Redis, aiosqlite.Connection]]:
        return self._database_connection


    # Running, closing and restarting the app

    async def start(self,
                    host: str=None,
                    port: int=None, 
                    path: str=None,
                    *,
                    debug: bool=False,
                    websocket: bool=False,
                    unix: bool=False,
                    websocket_timeout: float=20,
                    websocket_ping_interval: float=20,
                    websocket_ping_timeout: float=20,
                    websocket_max_size: int=None,
                    websocket_max_queue: int=None,
                    websocket_read_limit: int=2 ** 16,
                    websocket_write_limit: int=2 ** 16,
                    **kwargs):
        
        async def runner():
            return await run_server(self, self.loop, host, port, **kwargs)

        if websocket:
            async def runner():
                return await run_websocket_server(
                    self, self.loop, host, port,
                    timeout=websocket_timeout,
                    ping_interval=websocket_ping_interval,
                    ping_timeout=websocket_ping_timeout,
                    max_size=websocket_max_size,
                    max_queue=websocket_max_queue,
                    read_limit=websocket_read_limit,
                    write_limit=websocket_write_limit, **kwargs
                )

            if unix:
                async def runner():
                    return await run_unix_server(
                        self, self.loop, path, websocket=True,
                        websocket_timeout=websocket_timeout,
                        websocket_ping_interval=websocket_ping_interval,
                        websocket_ping_timeout=websocket_ping_timeout,
                        websocket_max_size=websocket_max_size,
                        websocket_max_queue=websocket_max_queue,
                        websocket_read_limit=websocket_read_limit,
                        websocket_write_limit=websocket_write_limit, **kwargs
                    )

        if unix and not websocket:
            async def runner():
                return await run_unix_server(
                    self, self.loop, path, **kwargs
                )

        async def actual():
            return await runner()

        if debug:
            async def actual():
                await self._watch_for_changes()
                return await runner()

        print(f'[{datetime.datetime.utcnow().strftime("%Y-%m-%d | %H:%M:%S")}] App running.')
        self._ready.set()

        self._start_tasks()
        return await actual()

    async def close(self):
        server = self._server
        if not server:
            raise AppError('The Application is not running')

        server.close()

        await self.dispatch('on_shutdown')
        await server.wait_closed()

    def run(self, *args, **kwargs):
        try:
            self.loop.run_until_complete(self.start(*args, **kwargs))
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.close())
        finally:
            self.loop.close()
            
    # websocket stuff

    def websocket(self, 
                  path: str, 
                  method: str, 
                  *, 
                  subprotocols=None):
        def decorator(coro):
            route = WebsocketRoute(path, method, coro)
            route.subprotocols = subprotocols

            return self.add_route(route, websocket=True)
        return decorator

    # Routing

    def add_route(self,
                  route: typing.Union[Route, WebsocketRoute],
                  *, 
                  websocket: bool=False):
        if not websocket:
            if not isinstance(route, Route):
                raise RouteRegistrationError('Expected Route but got {0!r} instead.'.format(route.__class__.__name__))

        if not inspect.iscoroutinefunction(route.coro):
            raise RouteRegistrationError('Routes must be async.')

        if route in self.router.routes:
            raise RouteRegistrationError('{0!r} is already a route.'.format(route.path))

        if websocket:
            if not isinstance(route, WebsocketRoute):
                fmt = 'Expected WebsocketRoute but got {0!r} instead'
                raise WebsocketRouteRegistrationError(fmt.format(route.__class__.__name__))

            self.router.add_route(route.path, route.method, route.coro, websocket=True)
            return route

        self.router.add_route(route.path, route.method, route.coro)
        return route

    def add_protected_route(self, 
                            path: typing.Union[str, yarl.URL],
                            method: str,
                            coro: typing.Coroutine):
        async def func(request: Request):
            token = request.token
            valid = self.validate_token(token)

            if not valid:
                return jsonify(message='Invalid Token.', status=403)

            return await coro(request)

        if isinstance(path, yarl.URL):
            path = path.raw_path

        route = Route(path, method, func)
        return self.add_route(route)

    def protected(self, path: typing.Union[str, yarl.URL], method: str):
        def decorator(func: typing.Coroutine):
            return self.add_protected_route(path, method, func)
        return decorator

    async def generate_oauth2_token(self,
                                    client_id: str, 
                                    client_secret: str, 
                                    *,
                                    validator: typing.Coroutine=None, 
                                    expires: int=60) -> typing.Optional[bytes]:
        if validator:
            await validator(client_secret)

        try:
            secret_key = self.settings.SECRET_KEY
            data = {
                'user' : client_id,
                'exp' : datetime.datetime.utcnow() + datetime.timedelta(minutes=expires)
            }
        
            token = jwt.encode(data, secret_key)
            return token
        except Exception:
            return None


    def validate_token(self, token: typing.Union[str, bytes]):
        secret = self.settings.SECRET_KEY

        try:
            data = jwt.decode(token, secret)
        except:
            return False

        return True

    def add_oauth2_login_route(self, 
                               path: typing.Union[str, yarl.URL],
                               method: str,
                               coro: typing.Coroutine=None,
                               validator: typing.Coroutine=None,
                               expires: int=60, *,
                               websocket_route: bool=False
                               ) -> typing.Union[Route, WebsocketRoute]:
        if isinstance(path, yarl.URL):
            path = path.raw_path

        if websocket_route:
            async def with_websocket(req: Request, websocket):
                client_id = req.headers.get('client_id')
                client_secret = req.headers.get('client_secret')

                if client_id and client_secret:
                    token = self.generate_oauth2_token(
                        client_id=client_id,
                        client_secret=client_secret,
                        validator=validator, 
                        expires=expires
                    )

                    if coro:
                        return await coro(req, websocket, token)
                    
                    return jsonify(access_token=token)

                if not client_secret or not client_id:
                    return abort(message='Missing client_id or client_secret.', status_code=403)

                route = WebsocketRoute(path, method, with_websocket)
                return self.add_route(route, websocket=True)

        async def without_websocket(request: Request):
            client_id = request.headers.get('client_id')
            client_secret = request.headers.get('client_secret')

            if client_id and client_secret:
                token = self.generate_oauth2_token(client_id, client_secret,
                                                validator=validator, expires=expires)

                if coro:
                    return await coro(request,token)
                
                return jsonify(access_token=token)

            if not client_secret or not client_id:
                return abort(message='Missing client_id or client_secret.', status_code=403)

        route = Route(path, method, without_websocket)
        return self.add_route(route)

    def oauth2(self,
               path: typing.Union[str, yarl.URL],
               method: str,
               validator: typing.Coroutine=None,
               expires: int=60, *,
               websocket_route: bool=False
               )-> typing.Union[Route, WebsocketRoute]:
        def decorator(func):
            return self.add_oauth2_login_route(
                path=path,
                method=method, 
                corr=func,
                validator=validator, 
                expires=expires,
                websocket_route=websocket_route
            )
        return decorator


    def get(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'GET', websocket_subprotocols)

            return self.route(path, 'GET')(func)
        return decorator

    def put(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'PUT', websocket_subprotocols)

            return self.route(path, 'PUT')(func)
        return decorator

    def post(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'POST', websocket_subprotocols)

            return self.route(path, 'POST')(func)
        return decorator

    def delete(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'DELETE', websocket_subprotocols)

            return self.route(path, 'DELETE')(func)
        return decorator

    def head(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'HEAD', websocket_subprotocols)

            return self.route(path, 'HEAD')(func)
        return decorator

    def options(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'OPTIONS', websocket_subprotocols)

            return self.route(path, 'OPTIONS')(func)
        return decorator

    def patch(self, 
            path: typing.Union[str, yarl.URL], 
            *, 
            websocket: bool=False, 
            websocket_subprotocols=None):
        def decorator(func):
            if websocket:
                return self.websocket(path, 'PATCH', websocket_subprotocols)

            return self.route(path, 'PATCH')(func)
        return decorator

    # dispatching

    async def dispatch(self, name: str, *args, **kwargs):
        try:
            listeners = self._listeners[name]
        except KeyError:
            return
        
        for listener in listeners:
            if isinstance(listener, asyncio.Future):
                print('here Future')

                if len(args) == 0:
                    listener.set_result(None)
                elif len(args) == 1:
                    listener.set_result(args[0])
                else:
                    listener.set_result(args)

                print(listener.result())
                listeners.remove(listener)
    
        return await asyncio.gather(*[listener(*args, **kwargs) for listener in listeners], loop=self.loop)

    # Shards

    def register_shard(self, shard: Shard):
        shard._inject(self)
        self.shards[shard.name] = shard

        return shard

    # Views

    def register_view(self, view: HTTPView, path: str):
        if not issubclass(view, HTTPView):
            raise ViewRegistrationError('Expected HTTPView but got {0!r} instead.'.format(view.__class__.__name__))

        for method in VALID_METHODS:
            if method.lower() in view.__dict__:
                coro = view.__dict__[method.lower()]

                route = Route(path, coro.__name__.upper(), coro)
                self.add_route(route)  

        self.views.append(view)
        return view

    def register_websocket_view(self, view: WebsocketHTTPView, path: str):
        if not issubclass(view, WebsocketHTTPView):
            raise ViewRegistrationError('Expected WebsocketHTTPView but got {0!r} instead.'.format(view.__class__.__name__))

        for method in VALID_METHODS:
            if method.lower() in view.__dict__:
                coro = view.__dict__[method.lower()]

                route = WebsocketRoute(path, coro.__name__.upper(), coro)
                self.add_route(route, websocket=True)  

        self.views.append(view)
        return view

    # Getting stuff

    def get_routes(self) -> typing.Iterator[typing.Union[Route, WebsocketRoute]]:
        for route in self.router.routes:
            yield route

    def get_shard(self, name: str):
        try:
            shard = self.shards[name]
        except KeyError:
            return None

        return shard
    
    # test client

    def request(self, route: str, method: str, **kwargs):
        if not self.__session or self.__session.closed:
            self.__session = aiohttp.ClientSession(loop=self.loop)

        url = self.settings.HOST + route
        session = self.__session

        return _RequestContextManager(session, url, method, **kwargs)

    # waiting for stuff

    async def wait_for(self, event: str, *, timeout: int=120.0):
        future = self.loop.create_future()
        listeners = self._listeners.get(event.lower())

        print(future)
        if not listeners:
            listeners = []
            self._listeners[event.lower()] = listeners

        listeners.append(future)
        return await asyncio.wait_for(future, timeout=timeout)