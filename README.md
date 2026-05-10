# Color Quiz Show

A tiny bilingual French/Vietnamese Django quiz app for live events.

The quiz is controlled from one hidden host page. Players join with a simple GET URL such as:

```text
/play/?code=ABCD
```

The host page displays the QR code and the short URL, then runs the full quiz automatically:

1. waiting room with live player join notifications,
2. question reading screen,
3. each color answer shown full screen in a fixed order,
4. 30-second answering phase,
5. result phase,
6. final top 5 podium and looping ranking pages.

## Minimal dependencies

- Django
- Django Channels with Daphne
- Pillow for image uploads in Django admin

This project intentionally uses the in-memory Channels layer to avoid Redis. That is perfect for a tiny single-process deployment, but do not run several server processes unless you switch to Redis.

## Install locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open:

```text
/admin/
```

Create a quiz and questions. Then open the hidden host URL shown in the admin.

## Create quiz content from commands

Create an empty quiz:

```bash
python manage.py create_quiz "Soiree quiz" --code LIVE --answer-duration 30
```

Add a question to an existing quiz:

```bash
python manage.py add_question \
  --quiz-code LIVE \
  --order 1 \
  --text-fr "Quelle est la capitale du Vietnam ?" \
  --text-vi "Thu do cua Viet Nam la thanh pho nao?" \
  --red-fr "Hanoi" --red-vi "Ha Noi" \
  --blue-fr "Ho Chi Minh-Ville" --blue-vi "Thanh pho Ho Chi Minh" \
  --green-fr "Hue" --green-vi "Hue" \
  --yellow-fr "Da Nang" --yellow-vi "Da Nang" \
  --correct-color red
```

Optional per-question timings can be added with `--question-read-duration` and `--answer-read-duration`.
When omitted, the app uses `DEFAULT_QUESTION_READING_DURATION_SECONDS` and
`DEFAULT_ANSWER_READING_DURATION_SECONDS` from `quiz/settings.py`.

Load a quiz from a JSON file:

```bash
python manage.py load_quiz quiz/samples/test_quiz.json --reset-db
```

Initialize a fresh test quiz with three sample questions:

```bash
python manage.py init_test_quiz --code TEST --reset-db
```

The command output includes the host URL and the player URL.

## Run with Daphne

```bash
daphne -b 0.0.0.0 -p 8000 color_quiz_show.asgi:application
```

## Deploy notes

For the fewest moving parts, deploy as one process. The in-memory WebSocket layer only works inside that process.

Suggested start command:

```bash
daphne -b 0.0.0.0 -p $PORT color_quiz_show.asgi:application
```

## Admin reset actions

The Quiz admin has two actions:

- Restart quiz: deletes answers only, keeps registered players.
- Full reset: deletes answers and registered players.

## Scoring

Players are ranked by:

1. correct answers descending,
2. average reaction time ascending,
3. join time ascending.
