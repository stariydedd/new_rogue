"""Геометрия карты: единственное место, где определены комнаты, коридоры и двери.

Все предикаты — чистые функции над комнатами и прямоугольниками коридоров.
Ими пользуются генератор уровня (размещение выхода), построение сетки символов,
логика бега и отрисовка троп — определения не могут разъехаться.

Коридор хранится как прямоугольник (x, y, w, h) с запасом в 1 клетку по
периметру; проходимая «центральная линия» — внутренность этого прямоугольника.
Дверь — клетка центральной линии коридора, лежащая на кольце стен комнаты.
"""


def passage_center_cells(passage):
    """Клетки центральной линии коридора (без расширения на ±1)."""
    x, y, w, h = passage
    return [(xx, yy)
            for yy in range(y + 1, y + h - 1)
            for xx in range(x + 1, x + w - 1)]


def in_passage_center(x, y, passages):
    """Лежит ли клетка на центральной линии хотя бы одного коридора."""
    return any(px + 1 <= x < px + pw - 1 and py + 1 <= y < py + ph - 1
               for px, py, pw, ph in passages)


def is_room_floor_cell(room, x, y):
    """Входит ли клетка в пол комнаты."""
    rx, ry, rw, rh = room.crd.x, room.crd.y, room.width, room.height
    return rx <= x < rx + rw and ry <= y < ry + rh


def is_room_wall_cell(room, x, y):
    """Является ли клетка внешней стеной данной комнаты."""
    rx, ry, rw, rh = room.crd.x, room.crd.y, room.width, room.height
    if x == rx - 1 or x == rx + rw:
        return ry <= y < ry + rh
    if y == ry - 1 or y == ry + rh:
        return rx <= x < rx + rw
    return False


def is_any_room_floor_cell(x, y, rooms):
    """Входит ли клетка в пол хотя бы одной комнаты."""
    return any(is_room_floor_cell(r, x, y) for r in rooms if r is not None)


def is_any_room_wall_cell(x, y, rooms):
    """Является ли клетка стеной хотя бы одной комнаты."""
    return any(is_room_wall_cell(r, x, y) for r in rooms if r is not None)


def is_corridor_cell(x, y, rooms, passages):
    """Клетка тропы: центральная линия коридора вне пола комнат (двери — да)."""
    return in_passage_center(x, y, passages) and not is_any_room_floor_cell(x, y, rooms)


def door_cells(rooms, passages):
    """Все двери уровня: клетки центральных линий коридоров на стенах комнат."""
    return {(x, y)
            for passage in passages
            for x, y in passage_center_cells(passage)
            if is_any_room_wall_cell(x, y, rooms)}


def path_cells(rooms, passages):
    """Клетки троп для отрисовки: коридоры (и двери) за вычетом пола комнат."""
    cells = set()
    for passage in passages:
        cells.update(passage_center_cells(passage))
    return {c for c in cells if not is_any_room_floor_cell(c[0], c[1], rooms)}
