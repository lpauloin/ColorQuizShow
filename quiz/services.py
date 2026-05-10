"""Pure service functions for timings, scoring, and state payloads."""
from django.conf import settings
from django.db.models import Avg, Count, FloatField, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .labels import LABELS
from .models import Answer, Player, Question, Quiz

COLOR_NAMES = {
    "red": {"fr": "Rouge", "vi": "Đỏ"},
    "blue": {"fr": "Bleu", "vi": "Xanh dương"},
    "green": {"fr": "Vert", "vi": "Xanh lá"},
    "yellow": {"fr": "Jaune", "vi": "Vàng"},
}

MEDALS = {
    1: {"type": "gold", "fr": "Or", "vi": "Vàng"},
    2: {"type": "silver", "fr": "Argent", "vi": "Bạc"},
    3: {"type": "bronze", "fr": "Bronze", "vi": "Đồng"},
}


def read_duration_ms(value, default_seconds):
    """Return an explicit question duration or the configured default."""
    seconds = value if value is not None else default_seconds
    return int(seconds) * 1000


def phase_duration_for_question(phase, question, quiz):
    """Return the duration of one automatic phase."""
    if phase == Quiz.PHASE_INTRO_QUESTION:
        return read_duration_ms(
            question.question_read_duration_seconds,
            settings.DEFAULT_QUESTION_READING_DURATION_SECONDS,
        )
    if phase == Quiz.PHASE_ANSWERING:
        return quiz.answer_duration_seconds * 1000
    if phase == Quiz.PHASE_RESULT:
        return settings.DEFAULT_RESULT_DURATION_SECONDS * 1000
    if phase.startswith("intro_"):
        return read_duration_ms(
            question.answer_read_duration_seconds,
            settings.DEFAULT_ANSWER_READING_DURATION_SECONDS,
        )
    return 3000


def get_question_top_answers(question, limit=5):
    """Return the fastest correct answers for a question, sorted by reaction time."""
    answers = (
        Answer.objects.filter(question=question, is_correct=True)
        .select_related("player")
        .order_by("response_time_ms")[:limit]
    )
    return [
        {
            "rank": i + 1,
            "name": answer.player.name,
            "response_time_ms": answer.response_time_ms,
        }
        for i, answer in enumerate(answers)
    ]


def get_rankings(quiz):
    """Return players ranked by correct answers and average reaction time."""
    players = (
        Player.objects.filter(quiz=quiz)
        .annotate(
            correct_count=Count("answers", filter=Q(answers__is_correct=True)),
            avg_reaction_time=Avg("answers__response_time_ms"),
            answered_count=Count("answers"),
        )
        .annotate(
            avg_reaction_time_sort=Coalesce(
                "avg_reaction_time",
                Value(999999999.0),
                output_field=FloatField(),
            )
        )
        .order_by("-correct_count", "avg_reaction_time_sort", "joined_at")
    )
    payload = []
    for rank, player in enumerate(players, start=1):
        payload.append({
            "player_id": player.id,
            "rank": rank,
            "name": player.name,
            "correct_count": player.correct_count or 0,
            "answered_count": player.answered_count or 0,
            "avg_reaction_time_ms": int(player.avg_reaction_time or 0),
            "medal": MEDALS.get(rank, {"type": "", "fr": "", "vi": ""}),
        })
    return payload


def get_player_result(quiz, player):
    """Return the final ranking row for one player."""
    for ranking in get_rankings(quiz):
        if ranking["player_id"] == player.id:
            return ranking
    return None


def build_quiz_state(quiz):
    """Build the shared state payload sent to host and players."""
    now = timezone.now()
    elapsed_ms = 0
    remaining_ms = quiz.phase_duration_ms
    if quiz.phase_started_at and quiz.phase_duration_ms:
        elapsed_ms = max(0, int((now - quiz.phase_started_at).total_seconds() * 1000))
        remaining_ms = max(0, quiz.phase_duration_ms - elapsed_ms)

    question = quiz.current_question.as_payload() if quiz.current_question else None
    return {
        "quiz": {"id": quiz.id, "title": quiz.title, "code": quiz.code, "status": quiz.status},
        "phase": quiz.current_phase,
        "question": question,
        "question_index": quiz.current_question.order if quiz.current_question else 0,
        "question_count": quiz.questions.count(),
        "participants_count": quiz.players.count(),
        "phase_duration_ms": quiz.phase_duration_ms,
        "elapsed_ms": elapsed_ms,
        "remaining_ms": remaining_ms,
        "labels": LABELS,
        "color_names": COLOR_NAMES,
        "rankings": get_rankings(quiz) if quiz.status == Quiz.STATUS_FINISHED else [],
        "question_top_answers": (
            get_question_top_answers(quiz.current_question)
            if quiz.current_question and quiz.current_phase == Quiz.PHASE_RESULT
            else []
        ),
    }


def build_player_state(player):
    """Build the state payload for a single player phone."""
    quiz = Quiz.objects.select_related("current_question").get(id=player.quiz_id)
    state = build_quiz_state(quiz)
    current_answer = None

    if quiz.current_question_id:
        answer = Answer.objects.filter(player=player, question_id=quiz.current_question_id).first()
        if answer:
            current_answer = {
                "color": answer.color,
                "is_correct": answer.is_correct,
                "response_time_ms": answer.response_time_ms,
            }

    state["player"] = {
        "id": player.id,
        "name": player.name,
        "language": player.language,
        "has_answered_current_question": current_answer is not None,
        "current_answer": current_answer,
        "result": get_player_result(quiz, player) if quiz.status == Quiz.STATUS_FINISHED else None,
    }
    return state


def record_answer(player, question, color, response_time_ms):
    """Store a player's answer if they have not answered this question yet."""
    return Answer.objects.get_or_create(
        player=player,
        question=question,
        defaults={
            "color": color,
            "is_correct": color == question.correct_color,
            "response_time_ms": max(0, int(response_time_ms)),
        },
    )
