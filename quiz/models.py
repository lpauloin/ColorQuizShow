"""Database models for the bilingual color quiz.

All comments are in English so the repository is ready for a public or private
GitHub project.
"""
import uuid
from django.db import models
from django.urls import reverse
from django.utils.crypto import get_random_string


class Quiz(models.Model):
    """A reusable quiz session configured from the Django admin."""

    STATUS_WAITING = "waiting"
    STATUS_RUNNING = "running"
    STATUS_FINISHED = "finished"

    PHASE_WAITING = "waiting_players"
    PHASE_INTRO_QUESTION = "intro_question"
    PHASE_INTRO_RED = "intro_red"
    PHASE_INTRO_BLUE = "intro_blue"
    PHASE_INTRO_GREEN = "intro_green"
    PHASE_INTRO_YELLOW = "intro_yellow"
    PHASE_ANSWERING = "answering"
    PHASE_RESULT = "result"
    PHASE_PODIUM = "podium"

    title = models.CharField(max_length=200)
    code = models.CharField(max_length=8, unique=True, blank=True)
    host_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, default=STATUS_WAITING)
    current_phase = models.CharField(max_length=30, default=PHASE_WAITING)
    current_question = models.ForeignKey(
        "Question",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_for_quizzes",
    )
    phase_started_at = models.DateTimeField(null=True, blank=True)
    phase_duration_ms = models.PositiveIntegerField(default=0)
    answer_duration_seconds = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_unique_code()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_unique_code():
        """Generate a short human-readable code for GET-only player URLs."""
        while True:
            code = get_random_string(4, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
            if not Quiz.objects.filter(code=code).exists():
                return code

    def get_play_url(self):
        return reverse("quiz:join") + f"?code={self.code}"

    def get_host_url(self):
        return reverse("quiz:host", kwargs={"host_token": self.host_token})

    def __str__(self):
        return self.title


class Question(models.Model):
    """One quiz question with four fixed color choices."""

    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"

    COLOR_CHOICES = [
        (RED, "Rouge / Đỏ"),
        (BLUE, "Bleu / Xanh dương"),
        (GREEN, "Vert / Xanh lá"),
        (YELLOW, "Jaune / Vàng"),
    ]

    COLOR_ORDER = [RED, BLUE, GREEN, YELLOW]

    quiz = models.ForeignKey(Quiz, related_name="questions", on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    text_fr = models.TextField("Question FR")
    text_vi = models.TextField("Question VI")
    image = models.ImageField(upload_to="quiz_questions/", blank=True, null=True)
    question_read_duration_seconds = models.PositiveIntegerField(
        "Question reading duration in seconds",
        blank=True,
        null=True,
    )
    answer_read_duration_seconds = models.PositiveIntegerField(
        "Answer reading duration in seconds",
        blank=True,
        null=True,
    )

    red_text_fr = models.TextField("Réponse rouge FR")
    red_text_vi = models.TextField("Réponse rouge VI")
    blue_text_fr = models.TextField("Réponse bleue FR")
    blue_text_vi = models.TextField("Réponse bleue VI")
    green_text_fr = models.TextField("Réponse verte FR")
    green_text_vi = models.TextField("Réponse verte VI")
    yellow_text_fr = models.TextField("Réponse jaune FR")
    yellow_text_vi = models.TextField("Réponse jaune VI")
    correct_color = models.CharField(max_length=10, choices=COLOR_CHOICES)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["quiz", "order"], name="unique_question_order_per_quiz"),
        ]

    def color_payload(self, color):
        """Return the bilingual text for one color."""
        answer_texts = {
            self.RED: (self.red_text_fr, self.red_text_vi),
            self.BLUE: (self.blue_text_fr, self.blue_text_vi),
            self.GREEN: (self.green_text_fr, self.green_text_vi),
            self.YELLOW: (self.yellow_text_fr, self.yellow_text_vi),
        }
        text_fr, text_vi = answer_texts[color]
        return {
            "color": color,
            "text_fr": text_fr,
            "text_vi": text_vi,
        }

    def as_payload(self):
        """Return a JSON-serializable representation for WebSocket messages."""
        return {
            "id": self.id,
            "order": self.order,
            "text_fr": self.text_fr,
            "text_vi": self.text_vi,
            "image_url": self.image.url if self.image else "",
            "question_read_duration_seconds": self.question_read_duration_seconds,
            "answer_read_duration_seconds": self.answer_read_duration_seconds,
            "colors": [self.color_payload(color) for color in self.COLOR_ORDER],
            "correct_color": self.correct_color,
        }

    def __str__(self):
        return f"{self.quiz.title} - Question {self.order}"


class Player(models.Model):
    """A participant who joined the quiz from a phone."""

    LANGUAGE_FR = "fr"
    LANGUAGE_VI = "vi"

    LANGUAGE_CHOICES = [
        (LANGUAGE_FR, "Français"),
        (LANGUAGE_VI, "Tiếng Việt"),
    ]

    quiz = models.ForeignKey(Quiz, related_name="players", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default=LANGUAGE_FR)
    session_key = models.CharField(max_length=80, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at"]

    def __str__(self):
        return self.name


class Answer(models.Model):
    """One answer from one player to one question."""

    player = models.ForeignKey(Player, related_name="answers", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, related_name="answers", on_delete=models.CASCADE)
    color = models.CharField(max_length=10, choices=Question.COLOR_CHOICES)
    is_correct = models.BooleanField(default=False)
    response_time_ms = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["player", "question"], name="one_answer_per_player_per_question"),
        ]
