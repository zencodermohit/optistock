class OptiStockException(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(self.message)


class ResourceNotFoundError(OptiStockException):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            code="NOT_FOUND", message=f"{resource} with ID {resource_id} was not found."
        )


class InsufficientStockError(OptiStockException):
    def __init__(self, message: str = "Insufficient stock to complete operation."):
        super().__init__(code="INSUFFICIENT_STOCK", message=message)
