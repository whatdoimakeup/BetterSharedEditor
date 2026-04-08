from django.db import models


class Room(models.Model):
    """Collaborative editing room stored in Tarantool via Django ORM."""

    id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    created_at = models.CharField(max_length=64)
    yjs_state = models.BinaryField(null=True, blank=True)
    content = models.TextField(blank=True, default="")
    updated_at = models.CharField(max_length=64)

    class Meta:
        db_table = "rooms"
        managed = False
        ordering = ("-updated_at", "-id")

    def __str__(self) -> str:
        return f"{self.id}: {self.name}"
