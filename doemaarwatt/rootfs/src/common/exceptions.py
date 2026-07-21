

class DMWException(Exception):
    '''Base exception for DoeMaarWatt system.
    '''
    def __init__(self, message: str, source: str, requires_fallback: bool = False) -> None:
        super().__init__(message)
        self.source = source
        self.requires_fallback = requires_fallback

    def __str__(self) -> str:
        return f'[{self.source}] {self.args[0]}' # Exception stores positional args from super().__init__(...) in self.args, so self.args[0] is the message


class ProgrammingError(DMWException):
    '''Exception raised when a likely programming error occurs which should be fixed
    '''
    def __init__(self, message: str, source: str, requires_fallback: bool = True) -> None:
        super().__init__(message, source, requires_fallback)


class ConfigException(DMWException):
    '''Exception raised due to misconfiguration, which should be fixed by the user before continuing
    '''
    def __init__(self, message: str, source: str, requires_fallback: bool = True) -> None:
        super().__init__(message, source, requires_fallback)
