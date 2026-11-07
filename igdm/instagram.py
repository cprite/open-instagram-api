"""The full client: DM transport/operations (IGDirect) + feature mixins."""
from .client import IGDirect, IGError, SessionExpired  # noqa: F401
from .read import ReadMixin
from .social import SocialMixin
from .publish import PublishMixin
from .dm import DMMixin
from .account import AccountMixin


class Instagram(AccountMixin, DMMixin, PublishMixin, SocialMixin, ReadMixin, IGDirect):
    pass
