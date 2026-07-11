"""Тесты конечного автомата игры: pygame headless (SDL dummy), без сети."""

import asyncio

import pygame
import pytest
from presentation.view import Game


@pytest.fixture(scope="module", autouse=True)
def pygame_display():
    pygame.init()
    pygame.display.set_mode((100, 100))
    yield
    pygame.quit()


def key(k, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=unicode)


@pytest.fixture()
def playing_game():
    game = Game()
    game.handle_event(key(pygame.K_RETURN))  # New Game -> NAME_ENTRY
    game.handle_event(key(pygame.K_RETURN))  # пустое имя -> PLAYING
    return game


def test_new_game_flow_reaches_playing(playing_game):
    assert playing_game.state == "PLAYING"
    assert playing_game.session is not None


def test_name_entry_typing_and_backspace():
    game = Game()
    game.handle_event(key(pygame.K_RETURN))
    assert game.state == "NAME_ENTRY"
    for ch in "hero":
        game.handle_event(key(0, unicode=ch))
    game.handle_event(key(pygame.K_BACKSPACE))
    assert game.name_input == "her"
    game.handle_event(key(pygame.K_RETURN))
    assert game.state == "PLAYING"
    assert game.player_name == "her"


def test_name_entry_escape_returns_to_menu():
    game = Game()
    game.handle_event(key(pygame.K_RETURN))
    game.handle_event(key(pygame.K_ESCAPE))
    assert game.state == "MAIN_MENU"


def test_movement_updates_stats(playing_game):
    # Игрок стартует внутри комнаты (минимум 4x3 пола), значит хотя бы одно из
    # четырёх направлений проходимо. Позицию сравнивать нельзя: W затем S
    # возвращает игрока в исходную клетку, хотя движение было.
    session = playing_game.session
    for k in (pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d):
        playing_game.handle_event(key(k))
    assert session.stats["tiles_moved"] > 0 or session.stats["attacks_made"] > 0


def test_item_menu_without_items_shows_message(playing_game):
    playing_game.handle_event(key(pygame.K_j))
    assert playing_game.state == "PLAYING"
    assert "No food" in playing_game.session.message


def test_quit_dialog_escape_resumes(playing_game):
    playing_game.handle_event(key(pygame.K_q))
    assert playing_game.state == "QUIT_DIALOG"
    playing_game.handle_event(key(pygame.K_ESCAPE))
    assert playing_game.state == "PLAYING"


def test_quit_dialog_confirm_returns_to_menu(playing_game):
    playing_game.handle_event(key(pygame.K_q))
    playing_game.handle_event(key(pygame.K_RETURN))  # "Return to Menu" (первая опция)
    assert playing_game.state == "MAIN_MENU"
    assert playing_game.session is None


def test_main_menu_has_only_new_and_scoreboard():
    from presentation.view import MAIN_MENU_OPTIONS
    assert [opt[1] for opt in MAIN_MENU_OPTIONS] == ["new", "scoreboard"]


def test_death_screen_returns_to_menu(playing_game):
    # _finish_run планирует отправку счёта через asyncio; в игре цикл всегда
    # запущен под asyncio.run, поэтому подкладываем event loop и здесь.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        playing_game.session.get_player().health = 0
        playing_game._check_game_over()
        assert playing_game.state == "DEATH"
        playing_game.handle_event(key(pygame.K_RETURN))
        assert playing_game.state == "MAIN_MENU"
        assert playing_game.session is None
    finally:
        loop.close()
        asyncio.set_event_loop(None)
