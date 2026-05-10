"""Management command for loading a quiz from JSON."""
from django.core.management.base import BaseCommand, CommandError

from quiz.loaders import QuizLoadError, load_quiz_from_json


class Command(BaseCommand):
    help = "Load a quiz and its questions from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("json_file", help="Path to the quiz JSON file.")
        parser.add_argument("--title", help="Override the quiz title from JSON.")
        parser.add_argument("--code", help="Override the quiz code from JSON.")
        parser.add_argument(
            "--answer-duration",
            type=int,
            help="Override the answering duration in seconds from JSON.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace an existing quiz that has the same code.",
        )
        parser.add_argument(
            "--reset-db",
            action="store_true",
            help="Delete all quiz data before loading the JSON file. Keeps users and migrations.",
        )

    def handle(self, *args, **options):
        try:
            result = load_quiz_from_json(
                options["json_file"],
                title=options.get("title"),
                code=options.get("code"),
                answer_duration_seconds=options.get("answer_duration"),
                replace=options["replace"],
                reset_db=options["reset_db"],
            )
        except QuizLoadError as exc:
            raise CommandError(str(exc)) from exc

        quiz = result.quiz
        action = "reset and loaded" if result.reset_db else "replaced" if result.replaced else "loaded"
        self.stdout.write(self.style.SUCCESS(f"Quiz {action}."))
        self.stdout.write(f"ID: {quiz.id}")
        self.stdout.write(f"Title: {quiz.title}")
        self.stdout.write(f"Code: {quiz.code}")
        self.stdout.write(f"Questions: {quiz.questions.count()}")
        self.stdout.write(f"Host URL: {quiz.get_host_url()}")
        self.stdout.write(f"Player URL: {quiz.get_play_url()}")
