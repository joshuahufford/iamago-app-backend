from django.db import migrations, models


def km_to_miles(apps, schema_editor):
    """Convert the values that were stored in kilometres."""
    RecommendationRequest = apps.get_model("directory", "RecommendationRequest")
    Recommendation = apps.get_model("directory", "Recommendation")

    for request in RecommendationRequest.objects.all().iterator():
        request.radius_miles = max(1, round(request.radius_miles * 0.621371))
        request.save(update_fields=["radius_miles"])

    for recommendation in Recommendation.objects.exclude(distance_miles=None).iterator():
        recommendation.distance_miles = round(recommendation.distance_miles * 0.621371, 2)
        recommendation.save(update_fields=["distance_miles"])


def miles_to_km(apps, schema_editor):
    RecommendationRequest = apps.get_model("directory", "RecommendationRequest")
    Recommendation = apps.get_model("directory", "Recommendation")

    for request in RecommendationRequest.objects.all().iterator():
        request.radius_miles = max(1, round(request.radius_miles / 0.621371))
        request.save(update_fields=["radius_miles"])

    for recommendation in Recommendation.objects.exclude(distance_miles=None).iterator():
        recommendation.distance_miles = round(recommendation.distance_miles / 0.621371, 2)
        recommendation.save(update_fields=["distance_miles"])


class Migration(migrations.Migration):
    """Switch stored distances from kilometres to miles.

    Renames first so existing rows survive, then converts the values in place.
    """

    dependencies = [("directory", "0001_initial")]

    operations = [
        migrations.RenameField(
            model_name="recommendationrequest",
            old_name="radius_km",
            new_name="radius_miles",
        ),
        migrations.RenameField(
            model_name="recommendation",
            old_name="distance_km",
            new_name="distance_miles",
        ),
        migrations.RunPython(km_to_miles, miles_to_km),
        migrations.AlterField(
            model_name="recommendationrequest",
            name="radius_miles",
            field=models.PositiveSmallIntegerField(default=25),
        ),
    ]
