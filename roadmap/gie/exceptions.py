class GIEServiceError(Exception):
    def __init__(self, message: str, *, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable
