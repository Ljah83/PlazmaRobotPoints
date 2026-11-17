import re
import math
import ezdxf

# ================= НАСТРОЙКИ =================
DST = "output.dxf"    # имя выходного DXF
START_X = 0.0
START_Y = 0.0
# =============================================


def parse_gcode_line(line):
    """Разбирает строку G-кода в словарь {буква: значение}.

    Возвращает {} для строк, в которых нет ни одной из команд движения
    G00 / G01 / G02 / G03. Это отсекает служебные строки вроде
    'G43 X2.619', 'G41', 'M50 H-0.001', 'F2200', 'G59 V509' и т.п.,
    чтобы их параметры (X, Y, I, J, R) не трактовались как перемещения.
    """
    # Убираем комментарии в скобках и после ;
    line = re.sub(r'\([^)]*\)', '', line)
    line = line.split(';')[0].strip().upper()
    if not line:
        return {}

    words = {}
    # Ищем все пары буква+число (поддерживает знаки, точки, экспоненту)
    pattern = r'([A-Z])([+-]?\d*\.?\d+(?:[Ee][+-]?\d+)?)'
    for match in re.finditer(pattern, line):
        letter = match.group(1)
        value = float(match.group(2))
        words[letter] = value

    # Проверяем, есть ли в строке хотя бы один код движения G00/G01/G02/G03.
    # G-код в G-коде может встречаться несколько раз в строке (например 'G90 G01'),
    # поэтому проверяем все вхождения 'G<число>'.
    has_motion = False
    for g_match in re.finditer(r'G\s*([+-]?\d+(?:\.\d+)?)', line):
        g_val = int(float(g_match.group(1)))
        if g_val in (0, 1, 2, 3):
            has_motion = True
            break

    if not has_motion:
        return {}

    return words


def get_arc_center_from_ij(start, end, i, j, clockwise):
    """
    Вычисляет центр дуги по смещениям I, J (относительно начала).
    I, J — смещения от начальной точки дуги до центра.
    """
    cx = start[0] + i
    cy = start[1] + j
    return (cx, cy)


def get_arc_angles(center, start, end, clockwise):
    """Возвращает начальный и конечный углы дуги в градусах для ezdxf."""
    def angle_from_center(pt):
        return math.degrees(math.atan2(pt[1] - center[1], pt[0] - center[0]))

    a_start = angle_from_center(start)
    a_end = angle_from_center(end)

    # Нормализуем углы в диапазон [0, 360)
    a_start %= 360.0
    a_end %= 360.0

    # ezdxf ожидает углы в градусах, дуга всегда против часовой стрелки от start до end.
    # Если движение по часовой (G02), нужно поменять местами start/end,
    # чтобы дуга шла в правильном направлении при отрисовке против часовой.
    if clockwise:
        # Для CW-дуги в DXF (которая всегда CCW) меняем начало и конец местами
        return a_end, a_start
    else:
        return a_start, a_end


def cnc_to_dxf(SRC, DST, START_X = START_X, START_Y = START_Y):
    """Конвертирует CNC код Pronest в dxf
    * SRC - Файл источник
    * DST - Сохраняемый файл после перерботки
    """

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Текущая позиция
    cur_x, cur_y = START_X, START_Y
    # Режим интерполяции: None , 'G00', 'G01', 'G02', 'G03'
    mode = None

    with open(SRC, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for line_num, raw_line in enumerate(lines, 1):
        words = parse_gcode_line(raw_line)
        if not words:
            continue

        # ---- Определяем режим движения ----
        # G00/G01/G02/G03 могут встречаться в строке; берём последний из них
        new_mode = None
        if "G" in words:
            g_val = int(words["G"])
            if g_val == 0:
                new_mode = "G00"
            elif g_val == 1:
                new_mode = "G01"
            elif g_val == 2:
                new_mode = "G02"
            elif g_val == 3:
                new_mode = "G03"
        if new_mode:
            mode = new_mode

        # ---- Вычисляем целевую позицию (всегда относительная) ----
        dx = words.get("X", 0.0)
        dy = words.get("Y", 0.0)

        target_x = cur_x + dx
        target_y = cur_y + dy

        # ---- Создаём геометрию в зависимости от режима ----
        if mode == "G00":
            # Линейное перемещение
            if dx != 0.0 or dy != 0.0:
                cur_x, cur_y = target_x, target_y

        elif mode == "G01":
            # Линейное перемещение
            if dx != 0.0 or dy != 0.0:
                cur_x, cur_y = target_x, target_y

        elif mode in ("G02", "G03"):
            # Дуговое перемещение
            # Определяем центр: либо через I/J, либо через R
            i = words.get("I", None)
            j = words.get("J", None)
            r = words.get("R", None)

            center = None
            if i is not None or j is not None:
                # I и J — смещения от текущей точки до центра
                i_val = i if i is not None else 0.0
                j_val = j if j is not None else 0.0
                center = get_arc_center_from_ij((cur_x, cur_y), (target_x, target_y), i_val, j_val, mode == "G02")
            elif r is not None:
                # Вычисление центра по радиусу (упрощённо для стандартного случая)
                # Вектор от начала к концу
                dx_arc = target_x - cur_x
                dy_arc = target_y - cur_y
                dist = math.hypot(dx_arc, dy_arc)
                if dist < 1e-9 or abs(r) < dist / 2.0 - 1e-6:
                    # Невозможная дуга — пропускаем
                    cur_x, cur_y = target_x, target_y
                    continue
                # Середина хорды
                mid_x = (cur_x + target_x) / 2.0
                mid_y = (cur_y + target_y) / 2.0
                # Высота сегмента
                h = math.sqrt(max(0.0, r * r - (dist / 2.0) ** 2))
                # Перпендикуляр к хорде
                perp_x = -dy_arc / dist
                perp_y = dx_arc / dist
                # Выбор стороны в зависимости от знака R и направления
                sign = 1.0
                if r < 0:
                    sign = -1.0
                # Для G02 (CW) и G03 (CCW) центр смещается в разные стороны
                if mode == "G02":
                    center = (mid_x + perp_x * h * sign, mid_y + perp_y * h * sign)
                else:
                    center = (mid_x - perp_x * h * sign, mid_y - perp_y * h * sign)
            else:
                # Нет данных для дуги — пропускаем
                cur_x, cur_y = target_x, target_y
                continue

            if center is None:
                cur_x, cur_y = target_x, target_y
                continue

            radius = math.hypot(cur_x - center[0], cur_y - center[1])
            clockwise = (mode == "G02")
            start_angle, end_angle = get_arc_angles(center, (cur_x, cur_y), (target_x, target_y), clockwise)

            # ezdxf: add_arc(center, radius, start_angle, end_angle) — всегда CCW
            msp.add_arc(
                center=(center[0], center[1]),
                radius=radius,
                start_angle=start_angle,
                end_angle=end_angle
            )
            cur_x, cur_y = target_x, target_y

        else:
            # Режим не задан или неизвестен — просто обновляем позицию (если есть X/Y)
            # но геометрию не создаём
            if dx != 0.0 or dy != 0.0:
                cur_x, cur_y = target_x, target_y

    doc.saveas(DST)
    print(f"Готово: {DST}")