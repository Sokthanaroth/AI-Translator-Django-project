from django.db import models

class TranslationHistory(models.Model):
    mode = models.CharField(max_length=50)
    source_text = models.TextField()
    result_text = models.TextField()
    explanation = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.mode} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

