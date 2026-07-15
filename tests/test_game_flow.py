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


def test_new_game_seed_differs_despite_fixed_rng_state():
    # В WASM интерпретатор стартует с одинаковым состоянием RNG на каждой
    # загрузке страницы; start_new_game обязан пересеять генератор часами,
    # иначе первый уровень всегда один и тот же.
    import random

    seeds = []
    for _ in range(2):
        random.seed(42)  # имитация одинакового состояния после загрузки страницы
        game = Game()
        game.handle_event(key(pygame.K_RETURN))
        game.handle_event(key(pygame.K_RETURN))
        seeds.append(game.session.level.seed)
    assert seeds[0] != seeds[1]


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


def test_item_menu_arrow_selection_uses_item(playing_game):
    # Выбор стрелками + Enter (путь тач-управления): вторая строка списка.
    from domain.domain import ItemType, Subject

    person = playing_game.session.get_player()
    for name in ("Bread", "Meat"):
        person.backpack.add_item(Subject(subject_type=ItemType.FOOD, health_effect=1, name=name))
    hp_before = person.health
    person.health = max(1, hp_before - 5)
    playing_game.handle_event(key(pygame.K_j))
    assert playing_game.state == "ITEM_MENU"
    playing_game.handle_event(key(pygame.K_DOWN))
    playing_game.handle_event(key(pygame.K_RETURN))
    assert playing_game.state == "PLAYING"
    assert "Meat" in playing_game.session.message
    assert all(it.name != "Meat" for it in person.backpack.items)


def test_run_moves_until_wall(playing_game):
    # Без врагов бег вправо должен довести до стены комнаты (или края тропы).
    from domain.businessLogic import can_move_to

    session = playing_game.session
    for room in session.get_rooms():
        if room is not None:
            room.enemies.clear()
            room.items.clear()
    person = session.get_player()
    # Ставим игрока к левому краю его комнаты — бег вправо детерминирован.
    player_room = next(
        r for r in session.get_rooms()
        if r is not None
        and r.crd.x <= person.crd.x < r.crd.x + r.width
        and r.crd.y <= person.crd.y < r.crd.y + r.height
    )
    person.crd.x = player_room.crd.x
    start_x = person.crd.x
    playing_game.handle_event(key(pygame.K_f))
    assert playing_game.pending_run
    playing_game.handle_event(key(pygame.K_d))
    assert not playing_game.pending_run
    assert person.crd.x > start_x  # пробежал больше одной клетки от старта
    # упёрся: правее стена, портал или дверь, либо проём сбоку (только в комнате,
    # как в правиле бега)
    from domain import geometry
    from domain.businessLogic import _door_beside

    nx, ny = person.crd.x + 1, person.crd.y
    exit_ahead = session.get_exit().x == nx and session.get_exit().y == ny
    beside_in_room = (_door_beside(session, 1, 0)
                      and geometry.is_any_room_floor_cell(person.crd.x, person.crd.y,
                                                          session.get_rooms()))
    assert (exit_ahead or not can_move_to(nx, ny, session)
            or (nx, ny) in session.level.doors or beside_in_room)


def test_corridor_turn_follows_single_continuation(playing_game):
    # На клетке коридора с единственным продолжением (не назад) бег поворачивает.
    import pytest as _pytest

    session = playing_game.session
    for room in session.get_rooms():
        if room is not None:
            room.enemies.clear()
    person = session.get_player()
    # ищем клетку тропы и направление входа, при котором прямо нельзя,
    # а продолжение ровно одно
    from domain import geometry
    from domain.businessLogic import _corridor_turn, build_grid_map, can_move_to
    rooms, passages = session.get_rooms(), session.get_passages()
    grid = build_grid_map(rooms, passages, person, session.get_exit())
    for y in range(len(grid)):
        for x in range(len(grid[0])):
            if not geometry.is_corridor_cell(x, y, rooms, passages):
                continue
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                person.crd.x, person.crd.y = x, y
                if can_move_to(x + dx, y + dy, session):
                    continue  # прямо можно — поворот не нужен
                turn = _corridor_turn(session, dx, dy)
                if turn is not None:
                    assert turn != (-dx, -dy)  # не разворот
                    tx, ty = x + turn[0], y + turn[1]
                    assert geometry.is_corridor_cell(tx, ty, rooms, passages)
                    return
    _pytest.skip("на этой карте не нашлось подходящего поворота")


def _clean_map_grid(playing_game):
    """Готовит детерминированную карту: без врагов и предметов; возвращает сетку."""
    from domain.businessLogic import build_grid_map

    session = playing_game.session
    for room in session.get_rooms():
        if room is not None:
            room.enemies.clear()
            room.items.clear()
    return build_grid_map(session.get_rooms(), session.get_passages(),
                          session.get_player(), session.get_exit())


def test_run_from_corridor_ends_in_doorway(playing_game):
    # Бег по коридору заканчивается в дверном проёме — дверь и есть конец коридора.
    import pytest as _pytest
    from domain.consts import SYM_CORRIDOR, SYM_DOOR

    grid = _clean_map_grid(playing_game)
    person = playing_game.session.get_player()
    for y in range(len(grid)):
        for x in range(2, len(grid[0])):
            if (grid[y][x] == SYM_DOOR
                    and grid[y][x - 1] == SYM_CORRIDOR and grid[y][x - 2] == SYM_CORRIDOR):
                doors = playing_game.session.level.doors
                if (x - 1, y - 1) in doors or (x - 1, y + 1) in doors:
                    continue  # боковой проём остановит бег раньше — не наш случай
                person.crd.x, person.crd.y = x - 2, y
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_d))
                assert (person.crd.x, person.crd.y) == (x, y)
                return
    _pytest.skip("на этой карте нет прямого захода в дверь слева")


def test_run_in_room_stops_before_door(playing_game):
    # Бег внутри комнаты в сторону двери встаёт на клетке перед ней.
    import pytest as _pytest
    from domain.consts import SYM_DOOR, SYM_ROOM_FLOOR

    grid = _clean_map_grid(playing_game)
    person = playing_game.session.get_player()
    for y in range(len(grid)):
        for x in range(len(grid[0]) - 2):
            if (grid[y][x] == SYM_DOOR
                    and grid[y][x + 1] == SYM_ROOM_FLOOR and grid[y][x + 2] == SYM_ROOM_FLOOR):
                doors = playing_game.session.level.doors
                if (x + 1, y - 1) in doors or (x + 1, y + 1) in doors:
                    continue  # боковой проём остановит бег раньше — не наш случай
                person.crd.x, person.crd.y = x + 2, y
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_a))
                assert (person.crd.x, person.crd.y) == (x + 1, y)
                return
    _pytest.skip("на этой карте нет двери на левой стене комнаты")


def test_run_next_to_door_passes_through_corridor(playing_game):
    # Стоя в комнате вплотную к двери, F в её сторону проносит через дверь
    # и дальше по коридору (а не останавливается перед дверью).
    import pytest as _pytest
    from domain.consts import SYM_CORRIDOR, SYM_DOOR, SYM_ROOM_FLOOR

    grid = _clean_map_grid(playing_game)
    person = playing_game.session.get_player()
    for y in range(len(grid)):
        for x in range(2, len(grid[0]) - 1):
            if (grid[y][x] == SYM_DOOR and grid[y][x + 1] == SYM_ROOM_FLOOR
                    and grid[y][x - 1] == SYM_CORRIDOR and grid[y][x - 2] == SYM_CORRIDOR):
                person.crd.x, person.crd.y = x + 1, y
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_a))
                assert person.crd.x <= x - 1  # дверь пройдена, бег ушёл в коридор
                return
    _pytest.skip("на этой карте нет двери с комнатой справа и коридором слева")


def test_run_from_doorway_crosses_room(playing_game):
    # Из дверного проёма F внутрь комнаты пересекает пол (минимум две клетки),
    # а не спотыкается о первую — обычное действие после каждого коридорного бега.
    import pytest as _pytest
    from domain.consts import SYM_DOOR, SYM_ROOM_FLOOR

    grid = _clean_map_grid(playing_game)
    person = playing_game.session.get_player()
    doors = playing_game.session.level.doors
    for y in range(len(grid)):
        for x in range(len(grid[0]) - 3):
            if (grid[y][x] == SYM_DOOR
                    and grid[y][x + 1] == SYM_ROOM_FLOOR
                    and grid[y][x + 2] == SYM_ROOM_FLOOR
                    and grid[y][x + 3] == SYM_ROOM_FLOOR
                    and not any((x + i, y + s) in doors for i in (1, 2) for s in (-1, 1))):
                person.crd.x, person.crd.y = x, y
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_d))
                assert person.crd.x >= x + 2  # пол пройден, не застряли на входе
                return
    _pytest.skip("на этой карте нет двери с тремя клетками пола справа")


def test_run_past_side_door_stops_next_to_it(playing_game):
    # Пробегая вдоль стены мимо проёма, бег встаёт на клетке рядом с дверью.
    import pytest as _pytest
    from domain.consts import SYM_DOOR, SYM_ROOM_FLOOR, SYM_WALL

    grid = _clean_map_grid(playing_game)
    person = playing_game.session.get_player()
    for y in range(2, len(grid)):
        for x in range(2, len(grid[0])):
            # Дверь в нижней стене (x, y); бежим направо по ряду пола (y-1).
            if (grid[y][x] == SYM_DOOR
                    and grid[y][x - 1] == SYM_WALL and grid[y][x - 2] == SYM_WALL
                    and grid[y - 1][x] == SYM_ROOM_FLOOR
                    and grid[y - 1][x - 1] == SYM_ROOM_FLOOR
                    and grid[y - 1][x - 2] == SYM_ROOM_FLOOR
                    and (x - 1, y - 2) not in playing_game.session.level.doors
                    and (x, y - 2) not in playing_game.session.level.doors):
                person.crd.x, person.crd.y = x - 2, y - 1
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_d))
                assert (person.crd.x, person.crd.y) == (x, y - 1)
                return
    _pytest.skip("на этой карте нет двери в нижней стене с пробегом вдоль неё")


def test_run_corridor_corner_turns_into_doorway(playing_game):
    # Угол коридора с дверью сразу за поворотом: бег поворачивает и
    # заканчивается в проёме, а не останавливается на углу (регрессия).
    import pytest as _pytest
    from domain.businessLogic import can_move_to
    from domain.consts import SYM_CORRIDOR, SYM_DOOR

    grid = _clean_map_grid(playing_game)
    session = playing_game.session
    person = session.get_player()
    for y in range(len(grid) - 1):
        for x in range(1, len(grid[0]) - 1):
            if (grid[y][x] == SYM_CORRIDOR and grid[y][x - 1] == SYM_CORRIDOR
                    and grid[y + 1][x] == SYM_DOOR
                    and not can_move_to(x + 1, y, session)
                    and not can_move_to(x, y - 1, session)):  # поворот единственный
                person.crd.x, person.crd.y = x - 1, y
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_d))
                assert (person.crd.x, person.crd.y) == (x, y + 1)
                return
    _pytest.skip("на этой карте нет угла коридора с дверью под поворотом")


def test_run_into_corridor_wall_does_nothing(playing_game):
    # Из коридора бег в непроходимую сторону — «невозможный ход», ноль движения.
    import pytest as _pytest
    from domain.businessLogic import can_move_to
    from domain.consts import SYM_CORRIDOR

    grid = _clean_map_grid(playing_game)
    session = playing_game.session
    person = session.get_player()
    for y in range(1, len(grid) - 1):
        for x in range(1, len(grid[0]) - 1):
            if (grid[y][x] == SYM_CORRIDOR
                    and grid[y][x - 1] == SYM_CORRIDOR and grid[y][x + 1] == SYM_CORRIDOR):
                person.crd.x, person.crd.y = x, y
                if can_move_to(x, y - 1, session):
                    continue  # вверх проходимо — не наш случай
                playing_game.handle_event(key(pygame.K_f))
                playing_game.handle_event(key(pygame.K_w))
                assert (person.crd.x, person.crd.y) == (x, y)
                assert session.message == "Can't move that way."
                return
    _pytest.skip("на этой карте нет горизонтального коридора с глухим верхом")


def test_run_while_sleeping_consumes_turn(playing_game):
    # F+направление во сне тратит ход, как обычный шаг: сон тикает, а не виснет.
    person = playing_game.session.get_player()
    person.special_state = {"sleeping": True, "turns": 3}
    playing_game.handle_event(key(pygame.K_f))
    playing_game.handle_event(key(pygame.K_d))
    assert playing_game.session.message == "You are asleep!"
    assert person.special_state.get("turns", 0) < 3

def test_run_into_adjacent_enemy_reports(playing_game):
    # Бег в упор к врагу не начинается, но и не выглядит мёртвым нажатием.
    from domain.domain import Coord, Opponent, OpponentType

    session = playing_game.session
    person = session.get_player()
    player_room = next(
        r for r in session.get_rooms()
        if r is not None
        and r.crd.x <= person.crd.x < r.crd.x + r.width
        and r.crd.y <= person.crd.y < r.crd.y + r.height
    )
    person.crd.x = player_room.crd.x  # у левого края: справа точно пол
    for room in session.get_rooms():
        if room is not None:
            room.enemies.clear()
    op = Opponent(opponent_type=OpponentType.ZOMBIE, health=100, agility=0, strength=0)
    op.crd = Coord(person.crd.x + 1, person.crd.y)
    player_room.enemies.append(op)
    start = (person.crd.x, person.crd.y)
    playing_game.handle_event(key(pygame.K_f))
    playing_game.handle_event(key(pygame.K_d))
    assert (person.crd.x, person.crd.y) == start
    assert session.message == "An enemy is in the way."

def test_run_cancelled_by_non_direction_key(playing_game):
    person = playing_game.session.get_player()
    start = (person.crd.x, person.crd.y)
    playing_game.handle_event(key(pygame.K_f))
    playing_game.handle_event(key(pygame.K_j))  # не направление — отмена
    assert not playing_game.pending_run
    assert (person.crd.x, person.crd.y) == start


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


def test_main_menu_options():
    from presentation.view import MAIN_MENU_OPTIONS
    assert [opt[1] for opt in MAIN_MENU_OPTIONS] == ["new", "scoreboard", "help"]


def test_help_from_menu_returns_to_menu():
    game = Game()
    game.handle_event(key(pygame.K_DOWN))
    game.handle_event(key(pygame.K_DOWN))  # выбор Help
    game.handle_event(key(pygame.K_RETURN))
    assert game.state == "HELP"
    game.handle_event(key(pygame.K_SPACE))
    assert game.state == "MAIN_MENU"


def test_help_from_game_returns_to_game(playing_game):
    playing_game.handle_event(key(pygame.K_F1))
    assert playing_game.state == "HELP"
    playing_game.handle_event(key(pygame.K_SPACE))
    assert playing_game.state == "PLAYING"


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
