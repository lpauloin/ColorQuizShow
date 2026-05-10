"""WebSocket consumers and the automatic quiz runner.

The automatic runner is intentionally lightweight. It is stored in process memory
because the project targets a tiny single-process deployment with minimal
infrastructure. For a multi-process deployment, move the runner state to Redis or
Django background tasks.
"""
import asyncio

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from .models import Player, Question, Quiz
from .services import build_player_state, build_quiz_state, phase_duration_for_question, record_answer

RUNNERS = {}
PAUSED = {}


@sync_to_async
def get_quiz_by_token(host_token):
    return Quiz.objects.get(host_token=host_token)


@sync_to_async
def get_player(player_id):
    return Player.objects.select_related("quiz").get(id=player_id)


@sync_to_async
def get_quiz_state(quiz_id):
    quiz = Quiz.objects.select_related("current_question").get(id=quiz_id)
    return build_quiz_state(quiz)


@sync_to_async
def get_player_quiz_state(player_id):
    player = Player.objects.select_related("quiz").get(id=player_id)
    return build_player_state(player)


@sync_to_async
def set_player_language(player_id, language):
    if language not in {Player.LANGUAGE_FR, Player.LANGUAGE_VI}:
        return None
    Player.objects.filter(id=player_id).update(language=language)
    player = Player.objects.select_related("quiz").get(id=player_id)
    return build_player_state(player)


@sync_to_async
def set_phase(quiz_id, question_id, phase):
    quiz = Quiz.objects.get(id=quiz_id)
    question = Question.objects.get(id=question_id) if question_id else None
    quiz.current_question = question
    quiz.current_phase = phase
    quiz.phase_duration_ms = phase_duration_for_question(phase, question, quiz) if question else 0
    quiz.phase_started_at = timezone.now()
    quiz.save(update_fields=["current_question", "current_phase", "phase_duration_ms", "phase_started_at"])
    return build_quiz_state(quiz)


@sync_to_async
def mark_running(quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    quiz.status = Quiz.STATUS_RUNNING
    quiz.current_phase = Quiz.PHASE_INTRO_QUESTION
    quiz.save(update_fields=["status", "current_phase"])


@sync_to_async
def mark_finished(quiz_id):
    quiz = Quiz.objects.get(id=quiz_id)
    quiz.status = Quiz.STATUS_FINISHED
    quiz.current_phase = Quiz.PHASE_PODIUM
    quiz.current_question = None
    quiz.phase_started_at = timezone.now()
    quiz.phase_duration_ms = 0
    quiz.save(update_fields=["status", "current_phase", "current_question", "phase_started_at", "phase_duration_ms"])
    return build_quiz_state(quiz)


@sync_to_async
def restart_in_db(quiz_id, full=False):
    quiz = Quiz.objects.get(id=quiz_id)
    if full:
        Player.objects.filter(quiz=quiz).delete()
    else:
        from .models import Answer
        Answer.objects.filter(player__quiz=quiz).delete()
    quiz.status = Quiz.STATUS_WAITING
    quiz.current_phase = Quiz.PHASE_WAITING
    quiz.current_question = None
    quiz.phase_started_at = None
    quiz.phase_duration_ms = 0
    quiz.save()
    return build_quiz_state(quiz)


@sync_to_async
def get_question_ids(quiz_id):
    return list(Question.objects.filter(quiz_id=quiz_id).order_by("order").values_list("id", flat=True))



@sync_to_async
def pause_in_db(quiz_id):
    quiz = Quiz.objects.select_related("current_question").get(id=quiz_id)
    state = build_quiz_state(quiz)
    quiz.phase_duration_ms = state["remaining_ms"]
    quiz.phase_started_at = None
    quiz.save(update_fields=["phase_duration_ms", "phase_started_at"])
    return build_quiz_state(quiz)


@sync_to_async
def resume_in_db(quiz_id):
    quiz = Quiz.objects.select_related("current_question").get(id=quiz_id)
    quiz.phase_started_at = timezone.now()
    quiz.save(update_fields=["phase_started_at"])
    return build_quiz_state(quiz)


async def broadcast_state(channel_layer, quiz_id):
    state = await get_quiz_state(quiz_id)
    await channel_layer.group_send(f"quiz_{quiz_id}", {"type": "state.message", "state": state})
    await channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})


async def wait_with_pause(quiz_id, duration_ms):
    """Sleep while honoring the host pause button."""
    remaining = duration_ms / 1000
    while remaining > 0:
        if PAUSED.get(quiz_id):
            await asyncio.sleep(0.2)
            continue
        step = min(0.2, remaining)
        await asyncio.sleep(step)
        remaining -= step


async def run_quiz(channel_layer, quiz_id):
    """Run the whole quiz timeline from first question to final loop."""
    try:
        await mark_running(quiz_id)
        question_ids = await get_question_ids(quiz_id)
        for question_id in question_ids:
            phases = [
                Quiz.PHASE_INTRO_QUESTION,
                Quiz.PHASE_INTRO_RED,
                Quiz.PHASE_INTRO_BLUE,
                Quiz.PHASE_INTRO_GREEN,
                Quiz.PHASE_INTRO_YELLOW,
                Quiz.PHASE_ANSWERING,
                Quiz.PHASE_RESULT,
            ]
            for phase in phases:
                state = await set_phase(quiz_id, question_id, phase)
                await channel_layer.group_send(f"quiz_{quiz_id}", {"type": "state.message", "state": state})
                await channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})
                await wait_with_pause(quiz_id, state["phase_duration_ms"])
        final_state = await mark_finished(quiz_id)
        await channel_layer.group_send(f"quiz_{quiz_id}", {"type": "state.message", "state": final_state})
        await channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": final_state})
    finally:
        RUNNERS.pop(quiz_id, None)
        PAUSED.pop(quiz_id, None)


class HostConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket for the hidden host page."""

    async def connect(self):
        self.quiz = await get_quiz_by_token(self.scope["url_route"]["kwargs"]["host_token"])
        self.host_group = f"host_{self.quiz.id}"
        await self.channel_layer.group_add(self.host_group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "state", "state": await get_quiz_state(self.quiz.id)})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.host_group, self.channel_name)

    async def receive_json(self, content):
        action = content.get("action")
        quiz_id = self.quiz.id
        if action == "start" and quiz_id not in RUNNERS:
            RUNNERS[quiz_id] = asyncio.create_task(run_quiz(self.channel_layer, quiz_id))
        elif action == "pause":
            PAUSED[quiz_id] = True
            state = await pause_in_db(quiz_id)
            await self.channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})
            await self.channel_layer.group_send(f"quiz_{quiz_id}", {"type": "state.message", "state": state})
            return
        elif action == "resume":
            PAUSED[quiz_id] = False
            state = await resume_in_db(quiz_id)
            await self.channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})
            await self.channel_layer.group_send(f"quiz_{quiz_id}", {"type": "state.message", "state": state})
            return
        elif action == "restart_answers":
            if quiz_id in RUNNERS:
                RUNNERS[quiz_id].cancel()
            state = await restart_in_db(quiz_id, full=False)
            await self.channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})
        elif action == "restart_full":
            if quiz_id in RUNNERS:
                RUNNERS[quiz_id].cancel()
            state = await restart_in_db(quiz_id, full=True)
            await self.channel_layer.group_send(f"host_{quiz_id}", {"type": "state.message", "state": state})
        await broadcast_state(self.channel_layer, quiz_id)

    async def state_message(self, event):
        await self.send_json({"type": "state", "state": event["state"], "paused": PAUSED.get(self.quiz.id, False)})

    async def player_joined(self, event):
        await self.send_json({**event, "type": "player_joined"})


class PlayerConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket for the smartphone player UI."""

    async def connect(self):
        self.player = await get_player(self.scope["url_route"]["kwargs"]["player_id"])
        self.quiz = self.player.quiz
        self.quiz_group = f"quiz_{self.quiz.id}"
        await self.channel_layer.group_add(self.quiz_group, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            f"host_{self.quiz.id}",
            {
                "type": "player.joined",
                "name": self.player.name,
                "player_id": self.player.id,
                "total_players": await sync_to_async(self.quiz.players.count)(),
            },
        )
        await self.send_json({"type": "state", "state": await get_player_quiz_state(self.player.id)})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.quiz_group, self.channel_name)

    async def receive_json(self, content):
        action = content.get("action")
        if action == "set_language":
            state = await set_player_language(self.player.id, content.get("language"))
            if state is None:
                await self.send_json({"type": "language_rejected"})
                return
            await self.send_json({"type": "state", "state": state})
            return

        if action != "answer":
            return
        color = content.get("color")
        if color not in Question.COLOR_ORDER:
            await self.send_json({"type": "answer_rejected", "reason": "invalid_color"})
            return

        state = await get_player_quiz_state(self.player.id)
        if state["phase"] != Quiz.PHASE_ANSWERING or not state["question"]:
            await self.send_json({"type": "answer_rejected", "reason": "too_late"})
            return
        question = await sync_to_async(Question.objects.get)(id=state["question"]["id"])
        response_time_ms = state["elapsed_ms"]
        answer, created = await sync_to_async(record_answer)(self.player, question, color, response_time_ms)
        await self.send_json({"type": "answer_saved", "created": created, "correct": answer.is_correct})
        await self.send_json({"type": "state", "state": await get_player_quiz_state(self.player.id)})

    async def state_message(self, event):
        await self.send_json({"type": "state", "state": await get_player_quiz_state(self.player.id)})
