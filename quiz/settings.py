"""Quiz app defaults.

These values are intentionally kept outside the project settings module so quiz
timing rules can be reused by commands, loaders, and runtime services.
"""
import os


DEFAULT_QUESTION_READING_DURATION_SECONDS = int(os.environ.get("DEFAULT_QUESTION_READING_DURATION_SECONDS", "6"))
DEFAULT_ANSWER_READING_DURATION_SECONDS = int(os.environ.get("DEFAULT_ANSWER_READING_DURATION_SECONDS", "4"))
DEFAULT_ANSWER_DURATION_SECONDS = int(os.environ.get("DEFAULT_ANSWER_DURATION_SECONDS", "10"))
DEFAULT_RESULT_DURATION_SECONDS = int(os.environ.get("DEFAULT_RESULT_DURATION_SECONDS", "6"))

# Public base URL used for QR codes and join links (e.g. an ngrok tunnel).
# Example: PUBLIC_BASE_URL=https://abc123.ngrok-free.app
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
