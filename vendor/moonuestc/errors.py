class ToolError(Exception):
    """Only stable, non-sensitive reason/stage values cross the CLI boundary."""
    def __init__(self, reason, stage="local", api_code=None, *, http_status=None, school_message=None):
        super().__init__(reason)
        self.reason, self.stage, self.api_code = reason, stage, api_code
        self.http_status, self.school_message = http_status, school_message


class AuthRequired(ToolError):
    pass
