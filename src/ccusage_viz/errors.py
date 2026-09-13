class VizError(Exception):
    """Base error with a localizable message key."""

    exit_code = 1

    def __init__(self, message_key: str, **values: object) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.values = values

    @property
    def key(self) -> str:
        return self.message_key


class UsageError(VizError):
    exit_code = 2


class QueryError(VizError):
    exit_code = 1


class SchemaError(VizError):
    exit_code = 1
