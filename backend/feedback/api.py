from ninja import Router
from ninja.responses import Status
from ninja.responses import Response
from ninja.security import SessionAuth
from ninja.utils import check_csrf

from feedback.models import Feedback
from feedback.schemas import FeedbackIn, FeedbackOut
from routing.models import RoutePlan

router = Router(tags=["feedback"])
session_auth = SessionAuth()


@router.post("/feedback", auth=session_auth, response={201: FeedbackOut, 401: dict, 403: dict, 404: dict})
def create_feedback(request, payload: FeedbackIn):
    if not request.user.is_authenticated:
        return Response({"detail": "Inicia sesión para enviar feedback."}, status=401)

    csrf_response = check_csrf(request)
    if csrf_response:
        return Response({"detail": "CSRF verification failed."}, status=403)

    try:
        route_plan = RoutePlan.objects.get(public_id=payload.route_plan_id, user=request.user)
    except RoutePlan.DoesNotExist:
        return Response({"detail": "Plan de ruta no encontrado."}, status=404)

    feedback = Feedback.objects.create(
        user=request.user,
        route_plan=route_plan,
        kind=payload.kind,
        comment=payload.comment,
    )
    return Status(201, {"id": feedback.id, "status": "stored"})
