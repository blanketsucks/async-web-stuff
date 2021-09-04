from __future__ import annotations
import io
from typing import Dict, List, Optional, TYPE_CHECKING, Tuple, TypeVar

from .utils import find_headers
from .file import File

if TYPE_CHECKING:
    from .request import Request

T = TypeVar('T')

__all__ = (
    'Disposition',
    'FormData'
)

def _get(iterable: List[T], index: int) -> Optional[T]:
    try:
        return iterable[index]
    except IndexError:
        return None

class Disposition:
    def __init__(self, header: str) -> None:
        self.header = header
        self._parts = self.header.split('; ')

    @property
    def content_type(self):
        return self._parts[0]

    @property
    def name(self):
        return _get(self._parts, 1)

    @property
    def filename(self):
        return _get(self._parts, 2)

class FormData:
    def __init__(self) -> None:
        self.files: List[Tuple[File, Optional[Disposition]]] = []

    def __iter__(self):
        return iter(self.files)

    def add_file(self, file: File, disposition: Optional[Disposition]) -> None:
        self.files.append((file, disposition))

    @classmethod
    def from_request(cls, request: Request) -> FormData:
        form = cls()
        data = request.text()

        content_type = request.headers.get('Content-Type')
        if not content_type:
            return form
        
        _, boundary = content_type.split('; ')
        boundary = '--' + boundary.strip('boundary=')

        data = data.strip(boundary + '--\r\n')
        split = data.split(boundary + '\r\n')
        
        for part in split:
            if part:
                try:
                    hdrs, body = find_headers(part.encode())
                    headers: Dict[str, str] = dict(hdrs) # type: ignore

                    content = headers.get('Content-Disposition')
                    if content:
                        disposition = Disposition(content)
                        filename = disposition.filename
                    else:
                        disposition = None
                        filename = None

                    data = io.BytesIO(body)
                    file = File(data, filename=filename)

                    form.add_file(file, disposition)
                except ValueError:
                    continue

        return form