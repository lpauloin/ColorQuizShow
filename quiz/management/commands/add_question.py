"""Management command for adding a question to an existing quiz."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from quiz.models import Question, Quiz


class Command(BaseCommand):
    help = "Add one question to an existing quiz."

    def add_arguments(self, parser):
        quiz_group = parser.add_mutually_exclusive_group(required=True)
        quiz_group.add_argument("--quiz-code", help="Join code of the target quiz.")
        quiz_group.add_argument("--quiz-id", type=int, help="Database ID of the target quiz.")

        parser.add_argument("--order", type=int, help="Question order. Defaults to the next available order.")
        parser.add_argument(
            "--question-read-duration",
            type=int,
            help="Question reading duration in seconds. Defaults to settings if omitted.",
        )
        parser.add_argument(
            "--answer-read-duration",
            type=int,
            help="Answer reading duration in seconds. Defaults to settings if omitted.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace the existing question at this order and clear its answers.",
        )

        parser.add_argument("--text-fr", required=True, help="Question text in French.")
        parser.add_argument("--text-vi", required=True, help="Question text in Vietnamese.")
        parser.add_argument("--red-fr", required=True, help="Red answer text in French.")
        parser.add_argument("--red-vi", required=True, help="Red answer text in Vietnamese.")
        parser.add_argument("--blue-fr", required=True, help="Blue answer text in French.")
        parser.add_argument("--blue-vi", required=True, help="Blue answer text in Vietnamese.")
        parser.add_argument("--green-fr", required=True, help="Green answer text in French.")
        parser.add_argument("--green-vi", required=True, help="Green answer text in Vietnamese.")
        parser.add_argument("--yellow-fr", required=True, help="Yellow answer text in French.")
        parser.add_argument("--yellow-vi", required=True, help="Yellow answer text in Vietnamese.")
        parser.add_argument(
            "--correct-color",
            required=True,
            choices=Question.COLOR_ORDER,
            help="Color that carries the correct answer.",
        )

    def handle(self, *args, **options):
        quiz = self.get_quiz(options)
        order = options.get("order")

        if order is not None and order <= 0:
            raise CommandError("--order must be greater than 0.")
        if options["question_read_duration"] is not None and options["question_read_duration"] <= 0:
            raise CommandError("--question-read-duration must be greater than 0.")
        if options["answer_read_duration"] is not None and options["answer_read_duration"] <= 0:
            raise CommandError("--answer-read-duration must be greater than 0.")

        with transaction.atomic():
            if order is None:
                max_order = quiz.questions.aggregate(max_order=Max("order"))["max_order"] or 0
                order = max_order + 1

            payload = {
                "text_fr": options["text_fr"],
                "text_vi": options["text_vi"],
                "red_text_fr": options["red_fr"],
                "red_text_vi": options["red_vi"],
                "blue_text_fr": options["blue_fr"],
                "blue_text_vi": options["blue_vi"],
                "green_text_fr": options["green_fr"],
                "green_text_vi": options["green_vi"],
                "yellow_text_fr": options["yellow_fr"],
                "yellow_text_vi": options["yellow_vi"],
                "correct_color": options["correct_color"],
                "question_read_duration_seconds": options["question_read_duration"],
                "answer_read_duration_seconds": options["answer_read_duration"],
            }

            question = quiz.questions.filter(order=order).first()
            if question and not options["replace"]:
                raise CommandError(
                    f"Question {order} already exists for quiz {quiz.code}. "
                    "Use --replace to update it."
                )
            if question:
                question.answers.all().delete()
                for field, value in payload.items():
                    setattr(question, field, value)
                question.save()
                created = False
            else:
                question = Question.objects.create(quiz=quiz, order=order, **payload)
                created = True

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Question {action}."))
        self.stdout.write(f"Quiz: {quiz.title} ({quiz.code})")
        self.stdout.write(f"Question ID: {question.id}")
        self.stdout.write(f"Order: {question.order}")

    def get_quiz(self, options):
        if options.get("quiz_id"):
            try:
                return Quiz.objects.get(id=options["quiz_id"])
            except Quiz.DoesNotExist as exc:
                raise CommandError(f'Quiz ID {options["quiz_id"]} does not exist.') from exc

        code = options["quiz_code"].strip().upper()
        try:
            return Quiz.objects.get(code=code)
        except Quiz.DoesNotExist as exc:
            raise CommandError(f'Quiz code "{code}" does not exist.') from exc
