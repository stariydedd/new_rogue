"""Тесты системы спрайтов и пользовательских переопределений."""

import pygame
import pytest
from presentation import sprites as sprites_mod
from presentation.config import SPRITE_SCALE, TILE_SIZE
from presentation.sprites import SpriteStore, parse_custom_name


@pytest.fixture(scope="module", autouse=True)
def pygame_display():
    pygame.init()
    pygame.display.set_mode((100, 100))
    yield
    pygame.quit()


def test_parse_custom_name_static():
    assert parse_custom_name("player") == ("player", 1)
    assert parse_custom_name("ogre") == ("ogre", 1)


def test_parse_custom_name_animated():
    assert parse_custom_name("player.4") == ("player", 4)
    assert parse_custom_name("wall.2") == ("wall", 2)


def test_all_game_roles_have_sprites():
    # Атласа больше нет: каждый PNG в assets/custom/ обязан существовать
    # для всех ролей, которые рисует ui.py и touch.py.
    from presentation.ui import ITEM_SPRITES, OPPONENT_SPRITES

    store = SpriteStore(SPRITE_SCALE)
    roles = {"player", "wall", "floor", "path", "portal", "heart", "tree", "decor"}
    roles |= set(OPPONENT_SPRITES.values()) | set(ITEM_SPRITES.values())
    for role in sorted(roles):
        assert store.has_custom(role), f"нет assets/custom/{role}.png"
        assert store.sprite(role) is not None
    assert not store.has_custom("definitely_not_a_role")


def test_custom_png_overrides_role(tmp_path, monkeypatch):
    # Кладём временный красный квадрат 32x32 как custom/player.png
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    surf = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
    surf.fill((255, 0, 0, 255))
    pygame.image.save(surf, str(custom_dir / "player.png"))
    monkeypatch.setattr(sprites_mod, "CUSTOM_DIR", custom_dir)

    store = SpriteStore(SPRITE_SCALE)
    assert store.has_custom("player")
    frame = store.sprite("player")
    assert frame.get_at((0, 0))[:3] == (255, 0, 0)


def test_flip_mirrors_frame_horizontally():
    store = SpriteStore(SPRITE_SCALE)
    normal = store.sprite("wall")
    flipped = store.sprite("wall", flip=True)
    w = normal.get_width()
    for x, y in [(0, 5), (3, 10), (w - 1, 20)]:
        assert flipped.get_at((x, y)) == normal.get_at((w - 1 - x, y))
    # повторный вызов отдаёт кадр из кэша, а не создаёт новый
    assert store.sprite("wall", flip=True) is flipped


def test_custom_animation_frames_split(tmp_path, monkeypatch):
    # PNG 128x32 с 4 кадрами -> роль отдаёт 4 разных кадра
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    strip = pygame.Surface((TILE_SIZE * 4, TILE_SIZE), pygame.SRCALPHA)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for i, c in enumerate(colors):
        strip.fill(c, (i * TILE_SIZE, 0, TILE_SIZE, TILE_SIZE))
    pygame.image.save(strip, str(custom_dir / "ogre.4.png"))
    monkeypatch.setattr(sprites_mod, "CUSTOM_DIR", custom_dir)

    store = SpriteStore(SPRITE_SCALE)
    assert store.has_custom("ogre")
    seen = {store.sprite("ogre", tick).get_at((TILE_SIZE // 2, TILE_SIZE // 2))[:3] for tick in range(4)}
    assert len(seen) == 4
