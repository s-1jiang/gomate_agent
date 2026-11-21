class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def not_found() -> AppError:
    return AppError("NOT_FOUND", "资源不存在", 404)
