"""Django admin configuration for creating and resetting quiz sessions."""
from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from .models import Answer, Player, Question, Quiz


class QuestionInline(admin.StackedInline):
    """Create questions directly inside the Quiz admin form."""

    model = Question
    extra = 1
    fields = (
        "order",
        "text_fr",
        "text_vi",
        "image",
        "question_read_duration_seconds",
        "answer_read_duration_seconds",
        "red_text_fr",
        "red_text_vi",
        "blue_text_fr",
        "blue_text_vi",
        "green_text_fr",
        "green_text_vi",
        "yellow_text_fr",
        "yellow_text_vi",
        "correct_color",
    )


@admin.action(description="Restart quiz: delete answers only")
def restart_quiz(modeladmin, request, queryset):
    """Reset scores while keeping player registrations."""
    for quiz in queryset:
        Answer.objects.filter(player__quiz=quiz).delete()
        quiz.status = Quiz.STATUS_WAITING
        quiz.current_phase = Quiz.PHASE_WAITING
        quiz.current_question = None
        quiz.phase_started_at = None
        quiz.phase_duration_ms = 0
        quiz.save()
    messages.success(request, "Quiz answers were deleted. Players were kept.")


@admin.action(description="Full reset: delete answers and players")
def full_reset_quiz(modeladmin, request, queryset):
    """Reset the whole session while keeping quiz content and URLs."""
    for quiz in queryset:
        Player.objects.filter(quiz=quiz).delete()
        quiz.status = Quiz.STATUS_WAITING
        quiz.current_phase = Quiz.PHASE_WAITING
        quiz.current_question = None
        quiz.phase_started_at = None
        quiz.phase_duration_ms = 0
        quiz.save()
    messages.success(request, "Quiz answers and player registrations were deleted.")


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "status", "question_count", "player_count", "host_link", "play_link")
    readonly_fields = ("code", "host_token", "host_link", "play_link", "qr_preview")
    actions = [restart_quiz, full_reset_quiz]
    inlines = [QuestionInline]
    fieldsets = (
        (None, {"fields": ("title", "code", "host_token", "answer_duration_seconds")}),
        ("Links", {"fields": ("host_link", "play_link", "qr_preview")}),
        ("Current state", {"fields": ("status", "current_phase", "current_question", "phase_started_at", "phase_duration_ms")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            admin_question_count=Count("questions", distinct=True),
            admin_player_count=Count("players", distinct=True),
        )

    def question_count(self, obj):
        return obj.admin_question_count

    def player_count(self, obj):
        return obj.admin_player_count

    def host_link(self, obj):
        if not obj.pk:
            return "Save first."
        return format_html('<a href="{}" target="_blank">Open hidden host page</a>', obj.get_host_url())

    def play_link(self, obj):
        if not obj.pk:
            return "Save first."
        return format_html('<a href="{}" target="_blank">Open player page</a>', obj.get_play_url())

    def qr_preview(self, obj):
        if not obj.pk:
            return "Save first."
        # This avoids adding a Python QR dependency. For offline QR generation, add a
        # small package such as segno and replace this external image URL.
        return format_html(
            '<img alt="QR code" width="220" height="220" src="https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={}" />',
            obj.get_play_url(),
        )


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "quiz",
        "order",
        "correct_color",
        "question_read_duration_seconds",
        "answer_read_duration_seconds",
    )
    list_filter = ("quiz", "correct_color")
    ordering = ("quiz", "order")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("quiz", "name", "language", "joined_at")
    list_filter = ("quiz", "language")


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ("player", "question", "color", "is_correct", "response_time_ms")
    list_filter = ("question__quiz", "is_correct", "color")
