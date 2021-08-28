from typing import Dict, Union, Optional
import importlib
import os
import pathlib

from .utils import SETTING_ENV_PREFIX
from .datastructures import ImmutableMapping

__all__ = (
    'Settings',
)

class Crendentials:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

class Authentication:
    def __init__(self):
        self._creditials: Dict[str, Crendentials] = {}

    def set_credentials_for(self, 
                            service: str, 
                            *, 
                            client_id: str, 
                            client_secret: str, 
                            redirect_uri: str):
        credentials = Crendentials(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri
        )
        self._creditials[service] = credentials
        return credentials

    def get_credentials_for(self, service: str) -> Optional[Crendentials]:
        return self._creditials.get(service)

    def __iter__(self):
        yield from self._creditials.items()

class Settings(ImmutableMapping[str, Union[str, int, bool]]):
    def __init__(self, defaults: Optional[Dict[str, Union[str, int, bool]]]=None) -> None:
        self.authentication = Authentication()
        if not defaults:
            defaults = {}

        super().__init__(**defaults)

    def __getitem__(self, k: str):
        return super().__getitem__(k.upper())

    @classmethod
    def from_file(cls, fp: Union[str, pathlib.Path]):
        self = cls()
        if isinstance(fp, pathlib.Path):
            fp = fp.name

        importlib.import_module(fp)      
        return self

    @classmethod
    def from_env_vars(cls):
        self = cls()
        envs = os.environ

        for name, _ in envs.items():
            if name.startswith(SETTING_ENV_PREFIX):
                _, _ = name.split(SETTING_ENV_PREFIX, maxsplit=1)

        return self

    def __repr__(self) -> str:
        return '<Settings>'
