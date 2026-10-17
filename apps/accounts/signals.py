from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Profile, User


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    """Every user gets a profile, so the API never has to handle a missing one."""
    if created:
        Profile.objects.get_or_create(user=instance)
