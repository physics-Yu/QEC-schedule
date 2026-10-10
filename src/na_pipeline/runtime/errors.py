"""Public, structured failures at the runtime boundary."""


class RuntimeContractError(ValueError):
    def __init__(self, code, message, *, action_id=None, resource_id=None, result_id=None):
        self.code = code
        self.action_id = action_id
        self.resource_id = resource_id
        self.result_id = result_id
        super().__init__(f"{code}: {message}")

    def to_dict(self):
        return {"code": self.code, "message": str(self), "action_id": self.action_id,
                "resource_id": self.resource_id, "result_id": self.result_id}


def fail(code, message, action=None, **context):
    raise RuntimeContractError(code, message, action_id=action.get("id") if action else None,
                               **context)
