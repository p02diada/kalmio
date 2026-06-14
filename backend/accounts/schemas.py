from ninja import Field, Schema


class AuthError(Schema):
    detail: str


class AuthUser(Schema):
    id: int | None = None
    email: str = ""
    authenticated: bool
    csrf_token: str | None = None


class AuthCredentials(Schema):
    email: str
    password: str = Field(..., min_length=8)


class CsrfResponse(Schema):
    detail: str
    csrf_token: str
