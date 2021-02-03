from .response import Response
import json

class AppError(Exception):
    """Base inheritance class for errors that occur during the Application's runtime."""
    pass

class BadConversion(AppError):
    pass

class HTTPException(Response, AppError):
    status_code = None

    def __init__(self, reason=None, content_type=None):

        self._reason = reason
        self._content_type = content_type
        
        if isinstance(reason, dict) or isinstance(reason, list):
            self._reason = json.dumps(reason)
            self._content_type = 'application/json'


        Response.__init__(self,
                        body=self._reason,
                        status=self.status_code,
                        content_type=self._content_type or "text/plain")

        AppError.__init__(self, self._reason)


class HTTPNotFound(HTTPException):
    status_code = 404


class HTTPBadRequest(HTTPException):
    status_code = 400


class HTTPFound(HTTPException):
    status_code = 302

    def __init__(self, location, reason=None, content_type=None):
        super().__init__(reason=reason, content_type=content_type)
        self.add_header("Location", location)

class EndpointError(AppError):
    pass

class EndpointLoadError(EndpointError):
    pass

class EndpointNotFound(EndpointError):
    pass

class ExtensionError(AppError):
    pass

class ExtensionLoadError(ExtensionError):
    pass

class ExtensionNotFound(ExtensionError):
    pass

class InvalidSetting(AppError):
    pass

class RegistrationError(AppError):
    pass        

class RouteRegistrationError(RegistrationError):
    pass

class ListenerRegistrationError(RegistrationError):
    pass

class MiddlewareRegistrationError(RegistrationError):
    pass
