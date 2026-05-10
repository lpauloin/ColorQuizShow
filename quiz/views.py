"""Small HTTP views for page rendering and player registration."""
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from .models import Player, Quiz


def home(request):
    """Fallback page for people who prefer typing the quiz code manually."""
    return render(request, "quiz/home.html")


def join(request):
    """Show the player name form for a GET-only quiz URL."""
    code = request.GET.get("code", "").strip().upper()
    quiz = Quiz.objects.filter(code=code).first() if code else None
    return render(request, "quiz/join.html", {"code": code, "quiz": quiz})


@csrf_exempt
@require_http_methods(["POST"])
def join_submit(request):
    """Register a player and redirect to the phone UI."""
    code = request.POST.get("code", "").strip().upper()
    name = request.POST.get("name", "").strip()
    language = request.POST.get("language", "").strip().lower()
    quiz = get_object_or_404(Quiz, code=code)

    if quiz.status != Quiz.STATUS_WAITING:
        messages.error(request, "Le quiz a déjà commencé. / Bài kiểm tra đã bắt đầu.")
        return redirect(f"/play/?code={quiz.code}")

    if not name:
        messages.error(request, "Nom obligatoire. / Vui lòng nhập tên.")
        return redirect(f"/play/?code={quiz.code}")

    allowed_languages = {Player.LANGUAGE_FR, Player.LANGUAGE_VI}
    if language not in allowed_languages:
        messages.error(request, "Langue obligatoire. / Vui lòng chọn ngôn ngữ.")
        return redirect(f"/play/?code={quiz.code}")

    if not request.session.session_key:
        request.session.save()

    player = Player.objects.create(
        quiz=quiz,
        name=name[:100],
        language=language,
        session_key=request.session.session_key or "",
    )
    return redirect("quiz:player", player_id=player.id)


def player(request, player_id):
    """Phone UI with four fixed color buttons."""
    player_obj = get_object_or_404(Player.objects.select_related("quiz"), id=player_id)
    return render(request, "quiz/player.html", {"player": player_obj, "quiz": player_obj.quiz})


def host(request, host_token):
    """Hidden host page used by the game master."""
    quiz = get_object_or_404(Quiz, host_token=host_token)
    base = settings.PUBLIC_BASE_URL
    absolute_play_url = (base + quiz.get_play_url()) if base else request.build_absolute_uri(quiz.get_play_url())
    return render(request, "quiz/host.html", {"quiz": quiz, "absolute_play_url": absolute_play_url})
