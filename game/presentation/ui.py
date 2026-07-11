import pygame
from domain.businessLogic import build_grid_map, compute_visibility, item_stat_label
from domain.consts import (
    COLS,
    PLAYER_NAME,
    ROWS,
    SYM_CORRIDOR,
    SYM_DOOR,
    SYM_EMPTY,
    SYM_EXIT,
    SYM_ITEM,
    SYM_PLAYER,
    SYM_ROOM_FLOOR,
    SYM_WALL,
)
from domain.domain import ItemType, OpponentType

from presentation.colors import (
    BLACK,
    GOLD,
    HILITE,
    HINT_COLOR,
    MSG_COLOR,
    PANEL_BG,
    WHITE,
)
from presentation.config import (
    ANIM_FRAME_MS,
    GRID_H,
    GRID_W,
    MAP_H,
    MAP_W,
    PANEL_H,
    SCREEN_H,
    SCREEN_W,
    TILE_SIZE,
)

# Клетки, под которыми рисуется пол: сетка отмечает предметы и игрока
# отдельными символами, но визуально это те же клетки пола.
FLOOR_SYMBOLS = (SYM_ROOM_FLOOR, SYM_CORRIDOR, SYM_DOOR, SYM_EXIT, SYM_ITEM, SYM_PLAYER)

# Значения — семантические роли (см. ROLE_DEFAULTS в sprites.py): игрок может
# переопределить любую своим PNG в assets/custom/<role>.png.
OPPONENT_SPRITES = {
    OpponentType.ZOMBIE: "pudge",
    OpponentType.VAMPIRE: "bloodseeker",
    OpponentType.GHOST: "ghost",
    OpponentType.OGRE: "axe",
    OpponentType.SNAKE: "skywrath",
}

ITEM_SPRITES = {
    ItemType.FOOD: "food",
    ItemType.ELIXIR: "elixir",
    ItemType.SCROLL: "scroll",
    ItemType.WEAPON: "sword",
    ItemType.TREASURE: "coin",
}

PLAYER_SPRITE = "player"

# Затемнение исследованных, но невидимых сейчас клеток.
EXPLORED_DIM_ALPHA = 175


def _blit(screen, font, text, pos, color):
    """Рисует одну строку текста в заданной точке (левый верхний угол)."""
    screen.blit(font.render(text, True, color), pos)


def _center_text(screen, font, text, y, color):
    """Рисует строку текста, отцентрированную по ширине экрана."""
    surf = font.render(text, True, color)
    rect = surf.get_rect(centerx=SCREEN_W // 2, y=y)
    screen.blit(surf, rect)


def _dim_background(screen):
    """Затемняет игровое поле полупрозрачным слоем (для диалогов поверх карты)."""
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))


def _anim_tick():
    return pygame.time.get_ticks() // ANIM_FRAME_MS


def _camera_offset(player):
    """Смещение камеры в пикселях: центр на игроке, с прижатием к краям карты."""
    px = player.crd.x * TILE_SIZE + TILE_SIZE // 2
    py = player.crd.y * TILE_SIZE + TILE_SIZE // 2
    cam_x = max(0, min(MAP_W - GRID_W, px - GRID_W // 2))
    cam_y = max(0, min(MAP_H - GRID_H, py - GRID_H // 2))
    return cam_x, cam_y


def _visible_cell_range(cam_x, cam_y):
    """Диапазон клеток карты, попадающих в кадр (с запасом в 1 тайл)."""
    x0 = max(0, cam_x // TILE_SIZE - 1)
    y0 = max(0, cam_y // TILE_SIZE - 1)
    x1 = min(COLS, (cam_x + GRID_W) // TILE_SIZE + 2)
    y1 = min(ROWS, (cam_y + GRID_H) // TILE_SIZE + 2)
    return x0, y0, x1, y1


def _cell_hash(x, y):
    """Детерминированный, но хорошо перемешанный хеш клетки.

    Линейная формула вида x*7+y*13 даёт строго периодичные узоры вдоль рядов
    (деревья «через каждые N клеток»); битовое перемешивание убирает
    периодичность, сохраняя стабильность между кадрами."""
    h = x * 374761393 + y * 668265263
    h = (h ^ (h >> 13)) * 1274126177
    return (h ^ (h >> 16)) & 0x7FFFFFFF


def _floor_variant(x, y):
    """Детерминированная вариация пола: floor_1..floor_8 по координатам клетки."""
    return f"floor_{_cell_hash(x, y) % 8 + 1}"


def _path_cells(passages, rooms):
    """Клетки троп: коридоры (и двери) за вычетом пола комнат.

    Сетка символов затирает клетку игрока/предмета маркером, поэтому тип
    земли под ними по ней не определить — считаем тропы из данных уровня."""
    cells = set()
    for px, py, pw, ph in passages:
        for yy in range(py + 1, py + ph - 1):
            for xx in range(px + 1, px + pw - 1):
                cells.add((xx, yy))
    for room in rooms:
        if room is None:
            continue
        for yy in range(room.crd.y, room.crd.y + room.height):
            for xx in range(room.crd.x, room.crd.x + room.width):
                cells.discard((xx, yy))
    return cells


def _blit_tile(screen, sprites, role, x, y, cam_x, cam_y, tick=0):
    """Рисует спрайт клетки (x, y) с учётом камеры, якорь — верхний левый угол тайла."""
    screen.blit(sprites.sprite(role, tick), (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))


def _blit_entity(screen, sprites, role, x, y, cam_x, cam_y, tick=0, flip=False):
    """Рисует персонажа с якорем по низу клетки: высокие спрайты возвышаются над тайлом."""
    frame = sprites.sprite(role, tick, flip)
    rect = frame.get_rect()
    rect.midbottom = (x * TILE_SIZE + TILE_SIZE // 2 - cam_x, (y + 1) * TILE_SIZE - cam_y)
    screen.blit(frame, rect)


def draw_map(screen, fonts, sprites, session):
    """Отрисовывает уровень: тайлы, предметы, персонажей и туман войны с камерой."""
    rooms = session.get_rooms()
    passages = session.get_passages()
    player = session.get_player()
    level_exit = session.get_exit()
    opponents = session.get_opponents()
    visible_opponents = [op for op in opponents if op.is_alive() and op.is_visible]

    base_grid = build_grid_map(rooms, passages, player, level_exit)
    fully_visible, wall_only = compute_visibility(session, base_grid)

    cam_x, cam_y = _camera_offset(player)
    x0, y0, x1, y1 = _visible_cell_range(cam_x, cam_y)
    tick = _anim_tick()
    path_cells = _path_cells(passages, rooms) if sprites.has_custom("path") else ()

    screen.fill(BLACK, (0, 0, GRID_W, GRID_H))

    dim = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
    dim.fill((0, 0, 0, EXPLORED_DIM_ALPHA))

    trees = []  # (x, y, hash) — деревья рисуются после тайлов, чтобы кроны не резались

    for y in range(y0, y1):
        for x in range(x0, x1):
            cell = base_grid[y][x]
            visible = (x, y) in fully_visible
            explored = (x, y) in wall_only
            # Для тайлов карты кадры кастомного PNG — пространственные варианты:
            # выбираются детерминированным хешем клетки, а не временем.
            cell_hash = _cell_hash(x, y)
            if cell == SYM_EMPTY or (not visible and not explored):
                # Пустота и неисследованное — сплошная чаща: карта выглядит как
                # поляны, прорубленные в лесу, а туман войны — как тёмный лес.
                _blit_tile(screen, sprites, "wall", x, y, cam_x, cam_y, cell_hash)
                if not visible:
                    screen.blit(dim, (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))
                elif sprites.has_custom("tree") and cell_hash % 5 == 0:
                    trees.append((x, y, cell_hash))
                continue
            if cell in FLOOR_SYMBOLS:
                # Тропы определяются по данным уровня (не по символу клетки —
                # его затирают маркеры игрока/предметов); остальной пол — "floor".
                if (x, y) in path_cells:
                    base_role = "path"
                elif sprites.has_custom("floor"):
                    base_role = "floor"
                else:
                    base_role = _floor_variant(x, y)
                _blit_tile(screen, sprites, base_role, x, y, cam_x, cam_y, cell_hash)
                if cell == SYM_EXIT:
                    _blit_tile(screen, sprites, "ladder", x, y, cam_x, cam_y)
                elif (cell == SYM_ROOM_FLOOR and visible
                        and sprites.has_custom("decor") and cell_hash % 11 == 0):
                    # Редкие кустики оживляют поляны.
                    _blit_tile(screen, sprites, "decor", x, y, cam_x, cam_y, cell_hash // 11)
            elif cell == SYM_WALL:
                _blit_tile(screen, sprites, "wall", x, y, cam_x, cam_y, cell_hash)
                if visible and sprites.has_custom("tree") and cell_hash % 4 == 0:
                    trees.append((x, y, cell_hash))
            if not visible:
                screen.blit(dim, (x * TILE_SIZE - cam_x, y * TILE_SIZE - cam_y))

    for x, y, cell_hash in trees:
        _blit_entity(screen, sprites, "tree", x, y, cam_x, cam_y, cell_hash)

    for room in rooms:
        if room is None:
            continue
        for item in room.items:
            if (item.crd.x, item.crd.y) in fully_visible:
                role = ITEM_SPRITES.get(item.type, "food")
                _blit_tile(screen, sprites, role, item.crd.x, item.crd.y, cam_x, cam_y, tick)

    for opponent in visible_opponents:
        if (opponent.crd.x, opponent.crd.y) not in fully_visible:
            continue
        role = OPPONENT_SPRITES.get(opponent.type, "pudge")
        _blit_entity(screen, sprites, role, opponent.crd.x, opponent.crd.y, cam_x, cam_y, tick,
                     flip=opponent.facing < 0)

    _blit_entity(screen, sprites, PLAYER_SPRITE, player.crd.x, player.crd.y, cam_x, cam_y, tick,
                 flip=player.facing < 0)


def _draw_hp_bar(screen, sprites, x, y, width, player):
    """Полоса здоровья с сердечком слева."""
    heart = sprites.sprite("ui_heart_full")
    screen.blit(heart, (x, y - 4))
    bar_x = x + heart.get_width() + 6
    ratio = player.health / player.max_health if player.max_health else 0
    pygame.draw.rect(screen, (60, 20, 20), (bar_x, y, width, 14))
    pygame.draw.rect(screen, (200, 50, 50), (bar_x, y, int(width * ratio), 14))
    pygame.draw.rect(screen, (20, 5, 5), (bar_x, y, width, 14), 2)


def draw_status_panel(screen, fonts, sprites, session):
    """Нижняя панель: портрет, HP-бар, характеристики, сообщение, подсказки."""
    player = session.get_player()
    pygame.draw.rect(screen, PANEL_BG, (0, GRID_H, SCREEN_W, PANEL_H))

    portrait = sprites.sprite(PLAYER_SPRITE, _anim_tick())
    screen.blit(portrait, (12, GRID_H + PANEL_H // 2 - portrait.get_height() // 2))

    text_x = 12 + portrait.get_width() + 14
    _blit(screen, fonts.ui, PLAYER_NAME, (text_x, GRID_H + 8), GOLD)
    _draw_hp_bar(screen, sprites, text_x, GRID_H + 36, 180, player)
    hp_label = f"{player.health}/{player.max_health}"
    _blit(screen, fonts.small, hp_label, (text_x + 44, GRID_H + 35), WHITE)

    weapon_name = f"{player.weapon.name} [+{player.weapon.strength_effect}]" if player.weapon else "Bare hands"
    stats = (
        f"STR {player.strength}   AGI {player.agility}   "
        f"DEPTH {session.level_num}   GOLD {player.treasures}   {weapon_name}"
    )
    _blit(screen, fonts.ui, stats, (text_x, GRID_H + 58), WHITE)

    if session.message:
        msg_surf = fonts.ui.render(session.message, True, MSG_COLOR)
        screen.blit(msg_surf, msg_surf.get_rect(topright=(SCREEN_W - 12, GRID_H + 10)))
    binds = "[WASD] Move  [H] Weapon  [J] Salve  [K] Bottle  [E] Tome  [Q] Menu"
    binds_surf = fonts.small.render(binds, True, HINT_COLOR)
    screen.blit(binds_surf, binds_surf.get_rect(bottomright=(SCREEN_W - 12, SCREEN_H - 8)))


def draw_playing(screen, fonts, sprites, session):
    """Полный кадр игрового процесса: карта + статус-панель."""
    draw_map(screen, fonts, sprites, session)
    draw_status_panel(screen, fonts, sprites, session)


def draw_item_menu_overlay(screen, fonts, items, allow_zero):
    """Рисует список предметов для выбора поверх нижней части карты."""
    lines = []
    if allow_zero:
        lines.append("0: Bare hands")
    for i, item in enumerate(items):
        lines.append(f"{i + 1}: {item.name}{item_stat_label(item)}")
    lines.append("ESC: cancel")

    box_h = 10 + len(lines) * 22
    box_y = GRID_H - box_h
    pygame.draw.rect(screen, (10, 10, 10), (0, box_y, SCREEN_W, box_h))
    pygame.draw.rect(screen, (90, 90, 90), (0, box_y, SCREEN_W, box_h), 1)
    for i, line in enumerate(lines):
        _blit(screen, fonts.ui, line, (10, box_y + 6 + i * 22), WHITE)


def _draw_dialog_box(screen, fonts, title, options, selected):
    """Рисует затемнение и центральное диалоговое окно с опциями."""
    _dim_background(screen)
    box_w, box_h = 520, 60 + len(options) * 40
    box_x = (SCREEN_W - box_w) // 2
    box_y = (SCREEN_H - box_h) // 2
    pygame.draw.rect(screen, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(screen, GOLD, (box_x, box_y, box_w, box_h), 2)
    _center_text(screen, fonts.ui, title, box_y + 16, WHITE)
    for i, (label, _) in enumerate(options):
        color = HILITE if i == selected else WHITE
        _center_text(screen, fonts.ui, label, box_y + 56 + i * 40, color)


def draw_quit_dialog(screen, fonts, options, selected):
    """Диалог подтверждения возврата в главное меню (текущий забег будет потерян)."""
    _draw_dialog_box(screen, fonts, "Return to menu? Run will be lost.", options, selected)


def _menu_backdrop(screen, sprites):
    """Фон экранов меню — сплошной чёрный."""
    screen.fill(BLACK)


def _title_with_shadow(screen, fonts, text, y):
    shadow = fonts.title.render(text, True, (60, 40, 0))
    surf = fonts.title.render(text, True, GOLD)
    rect = surf.get_rect(centerx=SCREEN_W // 2, y=y)
    screen.blit(shadow, rect.move(4, 4))
    screen.blit(surf, rect)


def draw_main_menu(screen, fonts, sprites, options, selected, message=""):
    """Главное меню: фон из тайлов, герой и выбор опций с маркером-мечом."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "NEW ROGUE", 130)

    hero = pygame.transform.scale_by(sprites.sprite(PLAYER_SPRITE, _anim_tick()), 3)
    screen.blit(hero, hero.get_rect(centerx=SCREEN_W // 2, y=210))

    menu_y = 360
    marker = pygame.transform.scale_by(sprites.sprite("sword"), 1)
    marker = pygame.transform.rotate(marker, -90)
    for i, (label, _) in enumerate(options):
        color = HILITE if i == selected else WHITE
        surf = fonts.menu.render(label, True, color)
        rect = surf.get_rect(centerx=SCREEN_W // 2, y=menu_y + i * 52)
        screen.blit(surf, rect)
        if i == selected:
            screen.blit(marker, marker.get_rect(midright=(rect.left - 18, rect.centery)))

    if message:
        _center_text(screen, fonts.ui, message, SCREEN_H - 60, MSG_COLOR)
    _center_text(screen, fonts.small, "WASD / arrows + Enter", SCREEN_H - 28, HINT_COLOR)


def draw_leaderboard_screen(screen, fonts, sprites, records, source=""):
    """Экран таблицы рекордов. records=None — глобальный топ ещё грузится."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "HIGH SCORES", 40)
    if source:
        _center_text(screen, fonts.small, source, 110, HINT_COLOR)
    header = (
        f"{'#':>3} {'NAME':<16} {'GOLD':>6} {'LVL':>4} {'KILLS':>5} {'FOOD':>4} "
        f"{'ELIX':>4} {'SCRL':>4} {'ATK':>5} {'HIT':>5} {'MOVE':>6}"
    )
    if records is None:
        _center_text(screen, fonts.ui, "Loading global leaderboard...", 170, WHITE)
    elif not records:
        _center_text(screen, fonts.ui, "No records yet.", 170, WHITE)
    else:
        _center_text(screen, fonts.small, header, 150, (170, 170, 170))
        for i, r in enumerate(records):
            name = str(r.get("player_name", "-"))[:16]
            line = (
                f"{i + 1:>3} {name:<16} {r['treasures']:>6} {r['level']:>4} {r['enemies_killed']:>5} "
                f"{r['food_used']:>4} {r['elixirs_used']:>4} {r['scrolls_read']:>4} "
                f"{r['attacks_made']:>5} {r['hits_taken']:>5} {r['tiles_moved']:>6}"
            )
            color = HILITE if i == 0 else WHITE
            _center_text(screen, fonts.small, line, 180 + i * 28, color)
    _center_text(screen, fonts.small, "Press any key to return...", SCREEN_H - 32, HINT_COLOR)


def draw_name_entry(screen, fonts, sprites, name_input):
    """Экран ввода имени игрока перед новой игрой."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, "YOUR NAME", 170)
    hero = pygame.transform.scale_by(sprites.sprite(PLAYER_SPRITE, _anim_tick()), 3)
    screen.blit(hero, hero.get_rect(centerx=SCREEN_W // 2, y=260))
    box_w, box_h = 460, 48
    box_x = (SCREEN_W - box_w) // 2
    box_y = 420
    pygame.draw.rect(screen, (25, 25, 25), (box_x, box_y, box_w, box_h))
    pygame.draw.rect(screen, GOLD, (box_x, box_y, box_w, box_h), 2)
    _blit(screen, fonts.menu, name_input + "_", (box_x + 14, box_y + 14), WHITE)
    _center_text(screen, fonts.small, "Enter: start   Esc: back   (empty = anonymous)",
                 box_y + box_h + 26, HINT_COLOR)


def draw_end_screen(screen, fonts, sprites, message, submit_status=""):
    """Экран смерти или победы со статусом отправки результата на сервер."""
    _menu_backdrop(screen, sprites)
    _title_with_shadow(screen, fonts, message, SCREEN_H // 2 - 80)
    if submit_status:
        _center_text(screen, fonts.ui, submit_status, SCREEN_H // 2 + 20, MSG_COLOR)
    _center_text(screen, fonts.small, "Press Enter to exit.", SCREEN_H // 2 + 60, HINT_COLOR)
