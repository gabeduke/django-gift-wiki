"""Metering and configuration for the in-app assistant.

Transcripts are deliberately absent: the conversation lives in the browser and
is never written here, so a gift secret can't reach the database or the nightly
GCS backups.
"""

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone


def current_period(when=None):
    """The month key usage is counted against, e.g. '2026-09'."""
    return (when or timezone.localdate()).strftime('%Y-%m')


class AssistantSettings(models.Model):
    """Operational knobs, editable in admin without a deploy.

    These are policy decisions that want changing from real data, which is why
    they are rows rather than constants. Things that change *behavior* rather
    than policy stay as module constants in the code that uses them.

    Reach the row through `load()`, and saving any instance writes row 1 (its
    `save()` forces `self.pk = 1`). That only covers the `.save()` path:
    `AssistantSettings.objects.create(...)` bypasses it — Django's `create()`
    forces an INSERT rather than routing through `save()`'s UPDATE-first
    branch — so creating a second row raises `IntegrityError` instead of
    silently overwriting row 1. That's deliberate: refusing loudly is safer
    than clobbering the family's spending caps.
    """

    per_user_monthly_messages = models.PositiveIntegerField(
        default=200, help_text='Messages one person may send per month'
    )
    global_monthly_messages = models.PositiveIntegerField(
        default=1000, help_text='Messages the whole family may send per month'
    )
    model_name = models.CharField(
        max_length=100,
        default='gemini-3.8-flash',
        help_text=(
            'Vertex AI model id. Confirm against the live publisher list rather than memory: '
            'curl the aiplatform publishers/google/models endpoint with an access token and '
            'an x-goog-user-project header, and pick a GA Flash model.'
        ),
    )
    enabled_until = models.DateField(
        null=True,
        blank=True,
        help_text='After this date the assistant hides itself. Blank means no end date.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Assistant Settings'
        verbose_name_plural = 'Assistant Settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        config, _ = cls.objects.get_or_create(pk=1)
        return config

    def __str__(self):
        return 'Assistant settings'


class AssistantUsage(models.Model):
    """What one person spent in one month.

    message_count is the enforced cap — 'you have 38 messages left' is legible
    to a ten-year-old in a way '$0.14' is not. Token totals are recorded but not
    enforced, so the caps can be set from real data rather than guesswork. The
    global ceiling is an aggregate over this table, which cannot drift out of
    sync the way a separate counter row would.
    """

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_usage'
    )
    period = models.CharField(max_length=7, help_text="Month key, e.g. '2026-09'")
    message_count = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-period', 'user_id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'period'], name='unique_usage_per_user_period')
        ]
        verbose_name = 'Assistant Usage'
        verbose_name_plural = 'Assistant Usage'

    def __str__(self):
        return f'{self.user} {self.period}: {self.message_count} messages'


class EasterEggFind(models.Model):
    """One person found one hidden egg, once.

    The slug and the moment, and deliberately nothing else: recording what they
    actually typed would be storing a transcript, which this feature does not
    do anywhere else and does not get to do here either.
    """

    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='easter_eggs'
    )
    slug = models.CharField(max_length=40)
    found_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['found_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'slug'], name='unique_egg_per_user')
        ]
        verbose_name = 'Easter Egg Find'
        verbose_name_plural = 'Easter Egg Finds'

    def __str__(self):
        return f'{self.user} found {self.slug}'
