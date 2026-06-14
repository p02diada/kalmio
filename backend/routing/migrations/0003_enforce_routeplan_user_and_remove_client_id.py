import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_orphan_route_plans(apps, schema_editor):
    RoutePlan = apps.get_model("routing", "RoutePlan")
    RoutePlan.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("routing", "0002_remove_routeplan_routing_rou_client__3dbfe9_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(delete_orphan_route_plans, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="routeplan",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="route_plans",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveField(
            model_name="routeplan",
            name="client_id",
        ),
    ]
