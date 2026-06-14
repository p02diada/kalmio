from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError
from django.middleware.csrf import get_token
from ninja import Router
from ninja.responses import Response
from ninja.utils import check_csrf

from accounts.schemas import AuthCredentials, AuthError, AuthUser, CsrfResponse
from accounts.security import check_auth_throttle, clear_auth_throttle, record_auth_failure

router = Router(tags=["auth"])
User = get_user_model()


@router.get("/auth/csrf", response=CsrfResponse)
def csrf(request):
    return {"detail": "csrf cookie set", "csrf_token": get_token(request)}


@router.get("/auth/me", response=AuthUser)
def me(request):
    user = request.user
    if not user.is_authenticated:
        return {"authenticated": False}

    return {"id": user.id, "email": user.email or user.get_username(), "authenticated": True}


@router.post("/auth/register", response={200: AuthUser, 400: AuthError, 403: AuthError, 429: AuthError})
def register(request, payload: AuthCredentials):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    email = payload.email.strip().lower()
    throttle = check_auth_throttle("register", email, request)
    if not throttle.allowed:
        return throttled_response(throttle.window_seconds)

    try:
        validate_email(email)
    except ValidationError:
        record_auth_failure("register", email, request)
        return Response({"detail": "Introduce un email válido."}, status=400)

    try:
        validate_password(payload.password)
        user = User.objects.create_user(username=email, email=email, password=payload.password)
    except ValidationError as exc:
        record_auth_failure("register", email, request)
        return Response({"detail": " ".join(exc.messages)}, status=400)
    except IntegrityError:
        record_auth_failure("register", email, request)
        return Response({"detail": "Ya existe una cuenta con ese email."}, status=400)

    clear_auth_throttle("register", email, request)
    login(request, user)
    return {"id": user.id, "email": user.email, "authenticated": True, "csrf_token": get_token(request)}


@router.post("/auth/login", response={200: AuthUser, 400: AuthError, 403: AuthError, 429: AuthError})
def login_view(request, payload: AuthCredentials):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    email = payload.email.strip().lower()
    throttle = check_auth_throttle("login", email, request)
    if not throttle.allowed:
        return throttled_response(throttle.window_seconds)

    user = authenticate(request, username=email, password=payload.password)
    if user is None:
        record_auth_failure("login", email, request)
        return Response({"detail": "Email o contraseña incorrectos."}, status=400)

    clear_auth_throttle("login", email, request)
    login(request, user)
    return {"id": user.id, "email": user.email or user.get_username(), "authenticated": True, "csrf_token": get_token(request)}


@router.post("/auth/logout", response={200: AuthUser, 403: AuthError})
def logout_view(request):
    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    logout(request)
    return {"authenticated": False, "csrf_token": get_token(request)}


def throttled_response(window_seconds: int) -> Response:
    retry_minutes = max(1, window_seconds // 60)
    return Response(
        {"detail": f"Demasiados intentos. Vuelve a intentarlo en {retry_minutes} minutos."},
        status=429,
    )
