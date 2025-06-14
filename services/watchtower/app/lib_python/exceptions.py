def format_exc(e: Exception):
    return f'exception="{e.__class__.__name__} {str(e).replace('"', "'")}"'

# https://stackoverflow.com/a/60465422/215945
class AppError(Exception):
    'base class for all custom exceptions for this application'

class DatabaseError(AppError):
    'custom exception for errors that occur during database operations'
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.log_msg      = kwargs.get('log_msg')
        self.log_kv_pairs = kwargs.get('log_kv_pairs', '')

class AppTimeoutError(AppError):
    'custom exception for when timeouts occur'
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.log_msg      = kwargs.get('log_msg')
        self.log_kv_pairs = kwargs.get('log_kv_pairs', '')

class ResourceError(AppError):
    'custom exception for errors that occur during resource management'
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.log_msg      = kwargs.get('log_msg')
        self.log_kv_pairs = kwargs.get('log_kv_pairs', '')

class WithDetailsError(AppError):
    'custom exception for unexpected errors/exceptions'
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.log_msg      = kwargs.get('log_msg')
        self.log_kv_pairs = kwargs.get('log_kv_pairs', '')
