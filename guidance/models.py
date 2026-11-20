from django.db import models


class Enquiry(models.Model):
    name = models.CharField(max_length=100)
    contact = models.CharField(max_length=30, db_index=True)
    interest = models.CharField(max_length=150, blank=True)
    opted_in = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class Suppression(models.Model):
    """A contact that opted out; no further calls are allowed."""
    contact = models.CharField(max_length=30, primary_key=True)


class CallSession(models.Model):
    STATES = [("consent", "Consent"), ("discovery", "Questions"), ("followup", "Follow-up"), ("closed", "Ended")]

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="sessions")
    language = models.CharField(max_length=8, default="en-IN")
    state = models.CharField(max_length=20, choices=STATES, default="consent")
    # Optimistic concurrency: a turn must quote the revision it was based on.
    revision = models.PositiveIntegerField(default=0)
    # Conversation, profile, recommendation, callback and outcome as one JSON document.
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def as_dict(self):
        return {"id": self.id, "enquiry_id": self.enquiry_id, "language": self.language,
                "state": self.state, "revision": self.revision, **self.data}
