from domain import geometry
from domain.combat import player_attacks_opponent, process_enemy_turns
from domain.consts import *
from domain.domain import OpponentType

FOG_RADIUS = 8
RUN_LIMIT = 200  # предохранитель от бесконечного бега


def _bresenham_line(x0, y0, x1, y1):
    """Возвращает список клеток прямой от (x0,y0) до (x1,y1)."""
    cells = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        cells.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return cells


def _compute_fov(px, py, grid, radius):
    """Ray casting из позиции игрока по алгоритму Брезенхэма."""
    visible = set()
    for tdy in range(-radius, radius + 1):
        for tdx in range(-radius, radius + 1):
            if tdx * tdx + tdy * tdy > radius * radius:
                continue
            tx, ty = px + tdx, py + tdy
            if not (0 <= tx < COLS and 0 <= ty < ROWS):
                continue
            for cx, cy in _bresenham_line(px, py, tx, ty):
                if not (0 <= cx < COLS and 0 <= cy < ROWS):
                    break
                if grid[cy][cx] == SYM_EMPTY:
                    break
                visible.add((cx, cy))
                if grid[cy][cx] == SYM_WALL:
                    break
    return visible


def _get_player_passage_cells(player_crd, passages):
    """Возвращает множество клеток проходов, в которых находится игрок."""
    cells = set()
    for passage in passages:
        px, py, pw, ph = passage
        rx, ry = px + 1, py + 1
        rw, rh = pw - 2, ph - 2
        if rx <= player_crd.x < rx + rw and ry <= player_crd.y < ry + rh:
            for y in range(ry, ry + rh):
                for x in range(rx, rx + rw):
                    cells.add((x, y))
    return cells


def _get_player_room_idx(player_crd, rooms):
    """Возвращает индекс комнаты, в которой стоит игрок, или -1 если в коридоре."""
    for i, room in enumerate(rooms):
        if room is None:
            continue
        if (room.crd.x <= player_crd.x < room.crd.x + room.width and
                room.crd.y <= player_crd.y < room.crd.y + room.height):
            return i
    return -1


def compute_visibility(session, grid):
    """
    Обновляет visited_rooms и возвращает (fully_visible, wall_only).
    fully_visible — клетки, где видно всё.
    wall_only — клетки посещённых комнат, где видны только стены.
    """
    rooms = session.get_rooms()
    player = session.get_player()

    room_idx = _get_player_room_idx(player.crd, rooms)

    px, py = player.crd.x, player.crd.y
    on_door = False
    if room_idx < 0:
        for i, room in enumerate(rooms):
            if room is None:
                continue
            rx, ry, rw, rh = room.crd.x, room.crd.y, room.width, room.height
            on_wall = (
                (px == rx - 1 or px == rx + rw) and (ry - 1 <= py <= ry + rh) or
                (py == ry - 1 or py == ry + rh) and (rx - 1 <= px <= rx + rw)
            )
            if on_wall:
                room_idx = i
                on_door = True
                break

    if room_idx >= 0:
        session.visited_rooms.add(room_idx)

    fully_visible = set()
    if room_idx >= 0:
        room = rooms[room_idx]
        for y in range(room.crd.y - 1, room.crd.y + room.height + 1):
            for x in range(room.crd.x - 1, room.crd.x + room.width + 1):
                if 0 <= x < COLS and 0 <= y < ROWS:
                    fully_visible.add((x, y))

        if on_door:
            fov = _compute_fov(px, py, grid, FOG_RADIUS)
            adj_corridor_cells = set()
            for passage in session.get_passages():
                cpx, cpy, cpw, cph = passage
                rpx, rpy = cpx + 1, cpy + 1
                rpw, rph = cpw - 2, cph - 2
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    if rpx <= px + dx < rpx + rpw and rpy <= py + dy < rpy + rph:
                        for yy in range(rpy, rpy + rph):
                            for xx in range(rpx, rpx + rpw):
                                adj_corridor_cells.add((xx, yy))
                        break
            for (x, y) in fov:
                if (x, y) in fully_visible:
                    continue
                if (x, y) in adj_corridor_cells:
                    fully_visible.add((x, y))
                elif grid[y][x] == SYM_DOOR:
                    if any((x+dx, y+dy) in adj_corridor_cells
                           for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]):
                        fully_visible.add((x, y))
    else:
        fov = _compute_fov(px, py, grid, FOG_RADIUS)
        player_corridor_cells = _get_player_passage_cells(player.crd, session.get_passages())
        for (x, y) in fov:
            if grid[y][x] == SYM_DOOR:
                if any((x+dx, y+dy) in player_corridor_cells
                       for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]):
                    fully_visible.add((x, y))
                continue
            if grid[y][x] == SYM_CORRIDOR and (x, y) not in player_corridor_cells:
                continue
            in_unvisited = any(
                idx not in session.visited_rooms
                and room is not None
                and room.crd.x - 1 <= x <= room.crd.x + room.width
                and room.crd.y - 1 <= y <= room.crd.y + room.height
                for idx, room in enumerate(rooms)
            )
            if not in_unvisited:
                fully_visible.add((x, y))

    wall_only = set()
    for idx in session.visited_rooms:
        if idx == room_idx:
            continue
        room = rooms[idx]
        if room is None:
            continue
        for y in range(room.crd.y - 1, room.crd.y + room.height + 1):
            for x in range(room.crd.x - 1, room.crd.x + room.width + 1):
                if 0 <= x < COLS and 0 <= y < ROWS and (x, y) not in fully_visible:
                    wall_only.add((x, y))

    return fully_visible, wall_only


def build_grid_map(rooms, passages, player, exit, opponents=None):
    """Строит двумерную сетку символов по текущему состоянию уровня."""
    grid = [[SYM_EMPTY for _ in range(COLS)] for _ in range(ROWS)]

    def in_bounds(x, y):
        """Проверяет, что координаты (x, y) лежат в пределах карты."""
        return 0 <= x < COLS and 0 <= y < ROWS

    def set_cell(x, y, value):
        """Записывает символ в клетку сетки, если координаты в пределах карты."""
        if in_bounds(x, y):
            grid[y][x] = value

    def draw_room(room):
        """Рисует стены и пол одной комнаты."""
        x, y, w, h = room.crd.x, room.crd.y, room.width, room.height
        left, right, top, bottom = x - 1, x + w, y - 1, y + h
        for xx in range(left, right + 1):
            set_cell(xx, top, SYM_WALL)
            set_cell(xx, bottom, SYM_WALL)
        for yy in range(top, bottom + 1):
            set_cell(left, yy, SYM_WALL)
            set_cell(right, yy, SYM_WALL)
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                set_cell(xx, yy, SYM_ROOM_FLOOR)

    for room in rooms:
        if room is not None:
            draw_room(room)

    corridor_cells = set()
    for passage in passages:
        corridor_cells.update(geometry.passage_center_cells(passage))

    for x, y in corridor_cells:
        if not geometry.is_any_room_floor_cell(x, y, rooms):
            set_cell(x, y, SYM_CORRIDOR)

    for x, y in corridor_cells:
        if geometry.is_any_room_wall_cell(x, y, rooms):
            set_cell(x, y, SYM_DOOR)

    for room in [r for r in rooms if r is not None]:
        for item in room.items:
            set_cell(item.crd.x, item.crd.y, SYM_ITEM)

    if opponents:
        for enemy in opponents:
            if enemy.is_alive():
                sym, _ = enemy.get_visual_representation()
                set_cell(enemy.crd.x, enemy.crd.y, sym)

    set_cell(exit.x, exit.y, SYM_EXIT)
    set_cell(player.crd.x, player.crd.y, SYM_PLAYER)

    return grid


def item_stat_label(item):
    """Возвращает строку вида '  [+50 HP, +10 AGI]' для предмета."""
    parts = []
    if item.health_effect:
        parts.append(f"+{item.health_effect} HP")
    if item.max_health_effect:
        parts.append(f"+{item.max_health_effect} MaxHP")
    if item.agility_effect:
        parts.append(f"+{item.agility_effect} AGI")
    if item.strength_effect:
        parts.append(f"+{item.strength_effect} STR")
    return f"  [{', '.join(parts)}]" if parts else ""


def can_move_to(x, y, session):
    """Проверяет, можно ли игроку встать на клетку (x, y)."""
    if not (0 <= x < COLS and 0 <= y < ROWS):
        return False
    grid = build_grid_map(
        session.get_rooms(), session.get_passages(),
        session.get_player(), session.get_exit()
    )
    return grid[y][x] in WALKABLE_SYMBOLS


def drop_item_near_player(session, item):
    """Кладёт предмет на ближайший свободный тайл пола рядом с игроком."""
    person = session.get_player()
    rooms = [r for r in session.get_rooms() if r is not None]
    grid = build_grid_map(rooms, session.get_passages(), person, session.get_exit())

    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
        nx, ny = person.crd.x + dx, person.crd.y + dy
        if not (0 <= nx < COLS and 0 <= ny < ROWS):
            continue
        if grid[ny][nx] not in {SYM_ROOM_FLOOR, SYM_CORRIDOR}:
            continue
        target_room = next(
            (r for r in rooms if r.crd.x <= nx < r.crd.x + r.width and r.crd.y <= ny < r.crd.y + r.height),
            min(rooms, key=lambda r: abs(r.crd.x + r.width // 2 - nx) + abs(r.crd.y + r.height // 2 - ny))
        )
        item.crd.x, item.crd.y = nx, ny
        target_room.items.append(item)
        return True
    return False


def _attack_message(op, damage, gold_gained=0):
    """Формирует текстовое сообщение об исходе атаки игрока."""
    name = opponent_display_name(op.type)
    if damage == -1:
        if op.type == OpponentType.VAMPIRE and not op.vampire_first_strike:
            return f"Your first strike against the {name} was deflected!"
        return f"You missed the {name}."
    if not op.is_alive():
        return f"You killed the {name} for {damage} dmg! Gained {gold_gained} gold."
    return f"You hit the {name} for {damage} dmg."


def move_person_x(session, direction):
    """Шаг игрока по горизонтали; если в клетке враг — атакует его."""
    person = session.get_player()
    # Разворот происходит даже если шаг упёрся в стену или врага.
    person.facing = 1 if direction > 0 else -1
    new_x = person.crd.x + direction
    new_y = person.crd.y

    for op in session.get_opponents():
        if op.is_alive() and op.crd.x == new_x and op.crd.y == new_y:
            gold_before = person.treasures
            damage = player_attacks_opponent(person, op)
            session.stats["attacks_made"] += 1
            if not op.is_alive():
                session.stats["enemies_killed"] += 1
            session.set_message(_attack_message(op, damage, person.treasures - gold_before))
            return True

    if can_move_to(new_x, new_y, session):
        person.crd.x = new_x
        session.stats["tiles_moved"] += 1
        return True

    session.set_message("Can't move that way.")
    return False


def move_person_y(session, direction):
    """Шаг игрока по вертикали; если в клетке враг — атакует его."""
    person = session.get_player()
    new_x = person.crd.x
    new_y = person.crd.y + direction

    for op in session.get_opponents():
        if op.is_alive() and op.crd.x == new_x and op.crd.y == new_y:
            gold_before = person.treasures
            damage = player_attacks_opponent(person, op)
            session.stats["attacks_made"] += 1
            if not op.is_alive():
                session.stats["enemies_killed"] += 1
            session.set_message(_attack_message(op, damage, person.treasures - gold_before))
            return True

    if can_move_to(new_x, new_y, session):
        person.crd.y = new_y
        session.stats["tiles_moved"] += 1
        return True

    session.set_message("Can't move that way.")
    return False


def check_exit(session):
    """Если игрок стоит на выходе — переводит его на следующий уровень. Возвращает True при переходе."""
    person = session.get_player()
    exit = session.get_exit()
    if person.crd.x == exit.x and person.crd.y == exit.y:
        next_level = session.level_num + 1
        session.update_level()
        session.set_message(f"You descend to level {next_level}.")
        return True
    return False


def check_item_pickup(session):
    """Автоматически подбирает предмет, если игрок стоит на его клетке."""
    person = session.get_player()
    for room in session.get_rooms():
        if room is None:
            continue
        for item in room.items[:]:
            if item.crd.x == person.crd.x and item.crd.y == person.crd.y:
                if person.pick_up_item(item):
                    room.items.remove(item)
                    session.set_message(f"Picked up: {item.name}{item_stat_label(item)}.")
                else:
                    session.set_message(f"Backpack full! Cannot pick up {item.name}.")


# --- Бег (find из оригинального Rogue) ---

def _corridor_turn(session, dx, dy):
    """Возвращает новое направление на повороте коридора или None.

    Поворот выполняется, только если игрок стоит на тропе и ровно одно
    направление (кроме обратного) продолжает её — развилки останавливают бег."""
    person = session.get_player()
    rooms, passages = session.get_rooms(), session.get_passages()
    if not geometry.is_corridor_cell(person.crd.x, person.crd.y, rooms, passages):
        return None
    options = []
    for ndx, ndy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        if (ndx, ndy) == (-dx, -dy):
            continue
        tx, ty = person.crd.x + ndx, person.crd.y + ndy
        if geometry.is_corridor_cell(tx, ty, rooms, passages) and can_move_to(tx, ty, session):
            options.append((ndx, ndy))
    return options[0] if len(options) == 1 else None


def _door_beside(session, dx, dy):
    """Дверь сбоку от направления движения — игрок пробегает мимо проёма."""
    person = session.get_player()
    x, y = person.crd.x, person.crd.y
    sides = ((x, y - 1), (x, y + 1)) if dx else ((x - 1, y), (x + 1, y))
    return any(side in session.level.doors for side in sides)


def run_direction(session, dx, dy):
    """Бег: серия ходов в направлении до упора; каждый шаг — полноценный ход.

    Бег по комнате останавливается на клетке перед дверью впереди и у двери,
    мимо которой пробегает (проём сбоку); но если игрок уже стоит вплотную
    к двери, шаг в её сторону проносит через дверь и дальше по коридору.
    Коридорный бег следует поворотам и заканчивается в дверном проёме на том
    конце (дверь — конец коридора). Также стоп: стена или развилка, враг,
    портал впереди (на бегу не спускаемся), полученный урон, подобранный
    предмет, сон или смерть. Если первый же шаг невозможен —
    «Can't move that way.» без движения. Вызывающий код проверяет конец игры
    после возврата."""
    person = session.get_player()
    opponents = session.get_opponents()
    rooms = session.get_rooms()
    doors = session.level.doors
    for step in range(RUN_LIMIT):
        if not person.is_alive() or person.special_state.get("sleeping"):
            break
        nx, ny = person.crd.x + dx, person.crd.y + dy
        if any(op.is_alive() and op.crd.x == nx and op.crd.y == ny for op in opponents):
            if step == 0:
                # Нажатие не должно выглядеть мёртвым: бег к врагу вплотную
                # не начинается, но игроку сообщается почему (атака — обычным шагом).
                session.set_message("An enemy is in the way.")
            break
        level_exit = session.get_exit()
        if level_exit.x == nx and level_exit.y == ny:
            session.set_message("You stop at the portal.")
            break
        entering_door = (nx, ny) in doors
        from_room = geometry.is_any_room_floor_cell(person.crd.x, person.crd.y, rooms)
        if entering_door and from_room and step:
            break  # разбежались по комнате — стоп перед дверью, не в ней
        if not can_move_to(nx, ny, session):
            # Поворот коридора — только когда уже бежим: нажатие в сторону
            # стены не должно начинать бег вбок.
            turn = _corridor_turn(session, dx, dy) if step else None
            if turn:
                dx, dy = turn
                continue
            if step == 0:
                session.set_message("Can't move that way.")
            break
        hp_before = person.health
        items_before = len(person.backpack.items)
        moved = move_person_x(session, dx) if dx else move_person_y(session, dy)
        if not moved:
            break
        check_item_pickup(session)
        check_exit(session)
        process_enemy_turns(session)
        if person.health < hp_before or len(person.backpack.items) != items_before:
            break
        if entering_door and not from_room:
            break  # прибежали по коридору в дверной проём — конец коридора
        # Стоп у бокового проёма — только в комнате: в коридоре дверь сбоку
        # от поворота — это его собственное продолжение, и бег должен доехать
        # до проёма, а не встать на углу.
        if (geometry.is_any_room_floor_cell(person.crd.x, person.crd.y, rooms)
                and _door_beside(session, dx, dy)):
            break  # пробегаем мимо прохода — стоп у двери
