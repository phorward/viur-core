from .default import DefaultRender as default
from .user import UserRender as user
from .file import FileRender as file
from viur.core import securitykey
import msgpack

__all__ = [default]


def genSkey(*args, **kwargs):
	return msgpack.dumps(securitykey.create())


genSkey.exposed = True


def _postProcessAppObj(obj):  # Register our SKey function
	obj["skey"] = genSkey
	return obj
