import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_orphan_feedback(apps, schema_editor):
    Feedback = apps.get_model("feedback", "Feedback")
    Feedback.objects.filter(user__isnull=True).delete()
    Feedback.objects.filter(route_plan__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("feedback", "0003_remove_feedback_conversation_id_and_more"),
        ("routing", "0003_enforce_routeplan_user_and_remove_client_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(delete_orphan_feedback, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="feedback",
            name="route_plan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="feedback",
                to="routing.routeplan",
            ),
        ),
        migrations.AlterField(
            model_name="feedback",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="feedback",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
