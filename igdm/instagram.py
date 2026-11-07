"""The full client: DM transport/operations (IGDirect) + feature mixins."""
from .client import IGDirect, IGError, SessionExpired  # noqa: F401
from .read import ReadMixin


class Instagram(ReadMixin, IGDirect):
    pass
