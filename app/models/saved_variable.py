from typing import Annotated, Any
from beanie import Document, Indexed, Link

from .timestamps import TimestampMixin
from .user import User
from .variable import Variable


class SavedVariable(Document, TimestampMixin):
    user: Annotated[Link[User], Indexed()]
    variable: Link[Variable]
    value: Any

    class Settings:
        name = "saved_variables"
        use_state_management = True
        indexes = [
            [("user", 1), ("variable", 1)],
        ]
