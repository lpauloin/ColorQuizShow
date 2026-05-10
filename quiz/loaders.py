"""Helpers for loading quiz content from JSON files."""
import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction

from .models import Question, Quiz


DEFAULT_SAMPLE_QUIZ_PATH = Path(__file__).resolve().parent / "samples" / "test_quiz.json"


class QuizLoadError(ValueError):
    """Raised when a quiz JSON file cannot be loaded safely."""


@dataclass(frozen=True)
class QuizLoadResult:
    quiz: Quiz
    created: bool
    replaced: bool
    reset_db: bool


def load_quiz_from_json(
    json_file,
    *,
    title=None,
    code=None,
    answer_duration_seconds=None,
    replace=False,
    reset_db=False,
):
    """Load a quiz and its questions from a JSON file."""
    path = Path(json_file)
    if not path.exists():
        raise QuizLoadError(f'Quiz JSON file "{path}" does not exist.')

    try:
        with path.open(encoding="utf-8") as quiz_file:
            data = json.load(quiz_file)
    except json.JSONDecodeError as exc:
        raise QuizLoadError(f'Quiz JSON file "{path}" is invalid JSON: {exc}') from exc

    return load_quiz_from_data(
        data,
        title=title,
        code=code,
        answer_duration_seconds=answer_duration_seconds,
        replace=replace,
        reset_db=reset_db,
    )


def load_quiz_from_data(
    data,
    *,
    title=None,
    code=None,
    answer_duration_seconds=None,
    replace=False,
    reset_db=False,
):
    """Load a quiz and its questions from a parsed JSON object."""
    if not isinstance(data, dict):
        raise QuizLoadError("Quiz JSON must contain an object at the top level.")

    quiz_title = clean_text(title) if title is not None else clean_text(data.get("title"))
    quiz_code = clean_code(code) if code is not None else clean_code(data.get("code", ""))
    quiz_answer_duration = (
        answer_duration_seconds
        if answer_duration_seconds is not None
        else data.get("answer_duration_seconds", settings.DEFAULT_ANSWER_DURATION_SECONDS)
    )
    questions = data.get("questions")

    validate_quiz_fields(quiz_title, quiz_code, quiz_answer_duration, questions)

    with transaction.atomic():
        quiz = None
        replaced = False

        if reset_db:
            Quiz.objects.all().delete()

        if quiz_code and not reset_db:
            quiz = Quiz.objects.filter(code=quiz_code).first()
            if quiz and not replace:
                raise QuizLoadError(f'A quiz with code "{quiz_code}" already exists. Use replace=True to reuse it.')

        if quiz:
            reset_quiz_content(quiz, quiz_title, quiz_answer_duration)
            replaced = True
        else:
            quiz = Quiz(title=quiz_title, answer_duration_seconds=quiz_answer_duration)
            if quiz_code:
                quiz.code = quiz_code
            quiz.save()

        seen_orders = set()
        for index, question_data in enumerate(questions, start=1):
            payload = normalize_question(question_data, index)
            if payload["order"] in seen_orders:
                raise QuizLoadError(f'Question order {payload["order"]} is duplicated.')
            seen_orders.add(payload["order"])
            Question.objects.create(quiz=quiz, **payload)

    return QuizLoadResult(quiz=quiz, created=not replaced, replaced=replaced, reset_db=reset_db)


def reset_quiz_content(quiz, title, answer_duration_seconds):
    quiz.players.all().delete()
    quiz.questions.all().delete()
    quiz.title = title
    quiz.answer_duration_seconds = answer_duration_seconds
    quiz.status = Quiz.STATUS_WAITING
    quiz.current_phase = Quiz.PHASE_WAITING
    quiz.current_question = None
    quiz.phase_started_at = None
    quiz.phase_duration_ms = 0
    quiz.save()


def normalize_question(data, index):
    if not isinstance(data, dict):
        raise QuizLoadError(f"Question {index} must be an object.")

    order = data.get("order", index)
    if not isinstance(order, int) or order <= 0:
        raise QuizLoadError(f"Question {index} must have a positive integer order.")

    correct_color = clean_text(data.get("correct_color"))
    if correct_color not in Question.COLOR_ORDER:
        raise QuizLoadError(f'Question {order} has an invalid correct_color "{correct_color}".')

    question_duration = clean_optional_positive_int(
        data.get("question_read_duration_seconds"),
        f"Question {order} question_read_duration_seconds",
    )
    answer_duration = clean_optional_positive_int(
        data.get("answer_read_duration_seconds"),
        f"Question {order} answer_read_duration_seconds",
    )

    payload = {
        "order": order,
        "text_fr": required_text(data, "text_fr", order),
        "text_vi": required_text(data, "text_vi", order),
        "question_read_duration_seconds": question_duration,
        "answer_read_duration_seconds": answer_duration,
        "correct_color": correct_color,
    }
    payload.update(normalize_answers(data, order))
    return payload


def normalize_answers(data, order):
    answers = data.get("answers")
    if isinstance(answers, dict):
        return normalize_nested_answers(answers, order)
    return normalize_flat_answers(data, order)


def normalize_nested_answers(answers, order):
    payload = {}
    for color in Question.COLOR_ORDER:
        answer = answers.get(color)
        if not isinstance(answer, dict):
            raise QuizLoadError(f"Question {order} is missing answer object for {color}.")
        payload[f"{color}_text_fr"] = required_text(answer, "text_fr", order, color)
        payload[f"{color}_text_vi"] = required_text(answer, "text_vi", order, color)
    return payload


def normalize_flat_answers(data, order):
    payload = {}
    for color in Question.COLOR_ORDER:
        payload[f"{color}_text_fr"] = required_text(data, f"{color}_text_fr", order)
        payload[f"{color}_text_vi"] = required_text(data, f"{color}_text_vi", order)
    return payload


def validate_quiz_fields(title, code, answer_duration_seconds, questions):
    if not title:
        raise QuizLoadError("Quiz title cannot be empty.")
    if code and len(code) > 8:
        raise QuizLoadError("Quiz code must be 8 characters or fewer.")
    if not isinstance(answer_duration_seconds, int) or answer_duration_seconds <= 0:
        raise QuizLoadError("answer_duration_seconds must be a positive integer.")
    if not isinstance(questions, list) or not questions:
        raise QuizLoadError("Quiz JSON must contain a non-empty questions list.")


def required_text(data, field, order, color=None):
    value = clean_text(data.get(field))
    if value:
        return value
    target = f"Question {order}"
    if color:
        target += f" answer {color}"
    raise QuizLoadError(f"{target} is missing required field {field}.")


def clean_text(value):
    return str(value).strip() if value is not None else ""


def clean_code(value):
    return clean_text(value).upper()


def clean_optional_positive_int(value, label):
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise QuizLoadError(f"{label} must be a positive integer or null.")
    return value
