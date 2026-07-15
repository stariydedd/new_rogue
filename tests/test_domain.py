"""Тесты доменной логики — без pygame и без сети."""

from domain.combat import opponent_attacks_player, player_attacks_opponent
from domain.consts import DEFAULT_MAX_HEALTH, MAX_BACKPACK_ITEMS_PER_TYPE
from domain.domain import (
    Coord,
    Level,
    Opponent,
    OpponentType,
    Person,
    Session,
    Subject,
)


def test_new_session_spawns_player_in_room():
    session = Session()
    player = session.get_player()
    rooms = [r for r in session.get_rooms() if r is not None]
    assert any(
        r.crd.x <= player.crd.x < r.crd.x + r.width and r.crd.y <= player.crd.y < r.crd.y + r.height
        for r in rooms
    )


def test_level_generates_minimum_rooms():
    for _ in range(5):
        level = Level(1)
        assert sum(1 for r in level.rooms if r is not None) >= 4


def test_persons_do_not_share_default_coord():
    """Регресс на мутабельный дефолт: у двух персонажей не должно быть общего Coord."""
    p1 = Person()
    p2 = Person()
    p1.crd.x = 42
    assert p2.crd.x != 42


def test_subjects_do_not_share_default_coord():
    s1 = Subject()
    s2 = Subject()
    s1.crd.x = 42
    assert s2.crd.x != 42


def test_player_damage_and_death():
    person = Person()
    person.take_damage(DEFAULT_MAX_HEALTH - 1)
    assert person.is_alive()
    person.take_damage(10)
    assert not person.is_alive()
    assert person.health == 0


def test_heal_capped_at_max_health():
    person = Person()
    person.take_damage(50)
    person.heal(9999)
    assert person.health == person.max_health


def test_backpack_type_limit():
    person = Person()
    for _ in range(MAX_BACKPACK_ITEMS_PER_TYPE):
        item = Subject()
        item.generate_food(person)
        assert person.pick_up_item(item)
    extra = Subject()
    extra.generate_food(person)
    assert not person.pick_up_item(extra)


def test_killing_opponent_grants_treasure():
    person = Person(strength=10**6, agility=10**6)  # гарантированное попадание и ваншот
    # strength=100 гарантирует лут > 0: формула 0.5*strength + randint(0,19),
    # с нулевыми статами randint может выпасть в 0 и тест станет флаки.
    opponent = Opponent(opponent_type=OpponentType.ZOMBIE, health=1, agility=0, strength=100)
    damage = player_attacks_opponent(person, opponent)
    assert damage > 0
    assert not opponent.is_alive()
    assert person.treasures > 0


def test_vampire_first_strike_always_deflected():
    person = Person(strength=10**6, agility=10**6)
    vampire = Opponent(opponent_type=OpponentType.VAMPIRE, health=100, agility=0, strength=0)
    assert player_attacks_opponent(person, vampire) == -1
    assert player_attacks_opponent(person, vampire) > 0


def test_vampire_drains_max_health():
    person = Person()
    vampire = Opponent(opponent_type=OpponentType.VAMPIRE, health=100, agility=10**6, strength=100)
    before = person.max_health
    damage = opponent_attacks_player(vampire, person)
    assert damage > 0
    assert person.max_health < before


def test_elixir_effect_expires():
    person = Person()
    elixir = Subject()
    elixir.generate_elixir(person)
    base = {"max_health": person.max_health, "agility": person.agility, "strength": person.strength}
    person.apply_elixir_effect(elixir)
    assert person.active_effects
    for _ in range(100):
        person.tick_effects()
    assert not person.active_effects
    assert person.max_health == base["max_health"]
    assert person.agility == base["agility"]
    assert person.strength == base["strength"]


def test_update_level_advances_and_moves_player():
    session = Session()
    session.update_level()
    assert session.level_num == 2
    assert session.get_player().crd != Coord(-1, -1)


def test_player_facing_follows_horizontal_moves():
    from domain.businessLogic import move_person_x

    session = Session()
    person = session.get_player()
    assert person.facing == 1
    move_person_x(session, -1)
    assert person.facing == -1  # разворот даже при шаге в стену
    move_person_x(session, 1)
    assert person.facing == 1


def test_opponent_faces_player_when_attacking():
    from domain.combat import process_enemy_turns

    session = Session()
    person = session.get_player()
    room = next(
        r for r in session.get_rooms()
        if r is not None
        and r.crd.x <= person.crd.x < r.crd.x + r.width
        and r.crd.y <= person.crd.y < r.crd.y + r.height
    )
    room.enemies.clear()
    op = Opponent(opponent_type=OpponentType.ZOMBIE, health=100, agility=0, strength=0)
    op.crd = Coord(person.crd.x - 1, person.crd.y)  # вплотную слева от игрока
    op.facing = -1
    room.enemies.append(op)
    process_enemy_turns(session)
    assert op.facing == 1  # повернулся к игроку (тот справа)


def test_exit_not_adjacent_to_room_doors():
    # Портал не спавнится вплотную к дверям комнаты (по Чебышёву > 1),
    # если в комнате есть хоть одна подходящая клетка.
    for _ in range(30):
        level = Level(1)
        exit_crd = level.exit_crd
        room = next(r for r in level.rooms
                    if r is not None
                    and r.crd.x <= exit_crd.x < r.crd.x + r.width
                    and r.crd.y <= exit_crd.y < r.crd.y + r.height)
        doors = level._door_cells(room)
        valid_exists = any(
            all(max(abs(x - dx), abs(y - dy)) > 1 for dx, dy in doors)
            for y in range(room.crd.y, room.crd.y + room.height - 1)
            for x in range(room.crd.x, room.crd.x + room.width - 1)
        )
        if valid_exists:
            assert all(max(abs(exit_crd.x - dx), abs(exit_crd.y - dy)) > 1
                       for dx, dy in doors), f"выход у двери: {exit_crd.x},{exit_crd.y}"
