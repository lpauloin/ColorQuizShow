"""Management command for creating an empty quiz."""
from django.core.management.base import BaseCommand, CommandError

from quiz.models import Quiz


class Command(BaseCommand):
    help = "Create an empty quiz."

    def add_arguments(self, parser):
        parser.add_argument("title", help="Quiz title.")
        parser.add_argument(
            "--code",
            help="Optional join code. If omitted, Django generates one.",
        )
        parser.add_argument(
            "--answer-duration",
            type=int,
            default=30,
            help="Answering duration in seconds. Defaults to 30.",
        )

    def handle(self, *args, **options):
        title = options["title"].strip()
        code = (options.get("code") or "").strip().upper()
        answer_duration = options["answer_duration"]

        if not title:
            raise CommandError("The quiz title cannot be empty.")
        if answer_duration <= 0:
            raise CommandError("--answer-duration must be greater than 0.")
        if code:
            if len(code) > 8:
                raise CommandError("--code must be 8 characters or fewer.")
            if Quiz.objects.filter(code=code).exists():
                raise CommandError(f'A quiz with code "{code}" already exists.')

        quiz = Quiz(title=title, answer_duration_seconds=answer_duration)
        if code:
            quiz.code = code
        quiz.save()

        self.stdout.write(self.style.SUCCESS("Quiz created."))
        self.stdout.write(f"ID: {quiz.id}")
        self.stdout.write(f"Title: {quiz.title}")
        self.stdout.write(f"Code: {quiz.code}")
        self.stdout.write(f"Host URL: {quiz.get_host_url()}")
        self.stdout.write(f"Player URL: {quiz.get_play_url()}")
