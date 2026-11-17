import ezdxf
from pathlib import Path
import sys
import math
import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, LabelFrame
import prepare_cnc

# Проверка наличия Pillow (нужен для JPG и BMP)
try:
    from PIL import Image, ImageTk
except ImportError:
    print("Ошибка: для работы скрипта требуется библиотека Pillow.")
    print("Установите её командой: pip install Pillow")
    input("Нажмите Enter для выхода...")
    sys.exit(1)

# === 0. Работа с конфигурационным файлом ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(SCRIPT_DIR, "img")
CFG_PATH = os.path.join(SCRIPT_DIR, "settings.cfg")
output_txt_file = "circles_centers.txt"
path_var = ""

def read_config(path):
    """
    Читает cfg-файл. Файл должен существовать.
    Возвращает:
      - values: dict ключ -> значение (строка)
      - lines: список строк файла
      - key_to_line: dict ключ -> индекс строки
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Конфигурационный файл не найден:\n{path}\n\n"
            f"Создайте файл settings.cfg в директории скрипта."
        )
    
    values = {}
    key_to_line = {}
    
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in line:
            key_part, _, val_part = line.partition("=")
            key = key_part.strip()
            val = val_part.split("#")[0].strip()
            values[key] = val
            key_to_line[key] = i
    
    return values, lines, key_to_line

def save_config(path, lines, key_to_line, new_values):
    """Сохраняет cfg, обновляя только значения ключей."""
    out_lines = list(lines)
    
    # 1. Обновляем или добавляем значения
    for key, new_val in new_values.items():
        if key in key_to_line:
            idx = key_to_line[key]
            # Проверка выхода за границы, если список изменился (маловероятно, но безопасно)
            if idx < len(out_lines):
                orig = out_lines[idx]
                m = re.match(r"^(\s*" + re.escape(key) + r"\s*=\s*)(.*?)(\s*#.*)?$", orig)
                if m:
                    prefix = m.group(1)
                    suffix = m.group(3) or ""
                    out_lines[idx] = prefix + str(new_val) + suffix
                else:
                    out_lines[idx] = f"{key} = {new_val}"
        else:
            # Ключа не было — добавляем в конец
            out_lines.append(f"{key} = {new_val}")
            # Обновляем карту, чтобы при последующих вызовах (если бы они были) ключ нашелся
            # Но так как мы перезаписываем файл целиком, это не критично для текущего вызова
    
    # 2. ИСПРАВЛЕНИЕ: Удаляем все пустые строки с конца списка
    while out_lines and out_lines[-1].strip() == "":
        out_lines.pop()
    
    # 3. Записываем файл в бинарном режиме, чтобы избежать автоматического преобразования переносов
    with open(path, "wb") as f:
        content = "\r\n".join(out_lines) + "\r\n"
        f.write(content.encode("utf-8"))

def load_image(path, size=None):
    """Загружает изображение через PIL. Если size задан — масштабирует."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Изображение не найдено: {path}")
    img = Image.open(path)
    if size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

# === Окно настроек ===
def show_settings_window():
    """
    Показывает окно с параметрами из settings.cfg.
    Возвращает (settings_dict, source_path) или (None, None) при выходе.
    """
    values, lines, key_to_line = read_config(CFG_PATH)
    
    root = tk.Tk()
    root.title("Настройки плазменной резки")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    
    # === Установка иконки окна ===
    logo_path = os.path.join(IMG_DIR, "logo.png")
    if os.path.isfile(logo_path):
        try:
            logo_img = load_image(logo_path)
            root.iconphoto(True, logo_img)
            root._logo_img = logo_img  # сохраняем ссылку
        except Exception as e:
            print(f"Не удалось загрузить иконку: {e}")
    
    # Общие стили
    PAD_X = 12
    PAD_Y = 6
    FRAME_PAD = 10
    
    main_frame = tk.Frame(root, padx=15, pady=15)
    main_frame.pack(fill="both", expand=True)
    
    row = 0
    
    # ============================================================
    # === 1. Выбор плазмы ===
    # ============================================================
    plasma_frame = LabelFrame(main_frame, text=" Выбор плазмы ", padx=FRAME_PAD, pady=FRAME_PAD)
    plasma_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
    plasma_frame.columnconfigure(1, weight=1)
    row += 1
    
    machine_var = tk.IntVar(value=int(values.get("machine", 1)))
    
    # Radio-кнопки в левой колонке
    rb_frame = tk.Frame(plasma_frame)
    rb_frame.grid(row=0, column=0, sticky="nw", padx=(0, 15))
    
    tk.Radiobutton(
        rb_frame, text="Плазма 1  (считает в минус)",
        variable=machine_var, value=1,
        font=("Arial", 10), anchor="w",
        command=lambda: update_plasma_view()
    ).pack(anchor="w", pady=2)
    
    tk.Radiobutton(
        rb_frame, text="Плазма 2  (считает в плюс)",
        variable=machine_var, value=2,
        font=("Arial", 10), anchor="w",
        command=lambda: update_plasma_view()
    ).pack(anchor="w", pady=2)
    
    # Картинка плазмы в правой колонке
    img_label = tk.Label(plasma_frame, borderwidth=1, relief="solid")
    img_label.grid(row=0, column=1, sticky="e")
    
    # Загружаем обе картинки заранее
    plazma1_path = os.path.join(IMG_DIR, "plazma1.jpg")
    plazma2_path = os.path.join(IMG_DIR, "plazma2.jpg")
    
    plazma1_img = load_image(plazma1_path, size=(180, 120))
    plazma2_img = load_image(plazma2_path, size=(180, 120))
    
    # Сохраняем ссылки, чтобы их не собрал сборщик мусора
    root._plazma1_img = plazma1_img
    root._plazma2_img = plazma2_img
    
    def update_plasma_view():
        """Обновляет картинку и видимость полей в зависимости от выбранной плазмы."""
        choice = machine_var.get()
        if choice == 1:
            img_label.configure(image=plazma1_img)
            # Показываем поля плазмы 1, скрываем плазмы 2
            entry_frame_1.grid()
            entry_frame_2.grid_remove()
        else:
            img_label.configure(image=plazma2_img)
            entry_frame_1.grid_remove()
            entry_frame_2.grid()
    
    # ============================================================
    # === 2. Параметры плазмы (динамические) ===
    # ============================================================
    params_frame = LabelFrame(main_frame, text=" Параметры плазмы ", padx=FRAME_PAD, pady=FRAME_PAD)
    params_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
    params_frame.columnconfigure(1, weight=1)
    row += 1
    
    entries = {}
    
    # --- Поля для плазмы 1 ---
    entry_frame_1 = tk.Frame(params_frame)
    entry_frame_1.grid(row=0, column=0, columnspan=2, sticky="ew")
    entry_frame_1.columnconfigure(1, weight=1)
    
    r1 = 0
    tk.Label(entry_frame_1, text="Стартовое положение доп. оси, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r1, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_sp1 = tk.StringVar(value=values.get("start_ext_position_1", ""))
    tk.Entry(entry_frame_1, textvariable=var_sp1, width=15, font=("Arial", 10)).grid(
        row=r1, column=1, sticky="w", pady=PAD_Y)
    entries["start_ext_position_1"] = (var_sp1, "int")
    r1 += 1
    
    tk.Label(entry_frame_1, text="Положение для разворота к кантователю, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r1, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_rp1 = tk.StringVar(value=values.get("reverse_ext_position_1", ""))
    tk.Entry(entry_frame_1, textvariable=var_rp1, width=15, font=("Arial", 10)).grid(
        row=r1, column=1, sticky="w", pady=PAD_Y)
    entries["reverse_ext_position_1"] = (var_rp1, "int")
    
    # --- Поля для плазмы 2 ---
    entry_frame_2 = tk.Frame(params_frame)
    entry_frame_2.columnconfigure(1, weight=1)
    
    r2 = 0
    tk.Label(entry_frame_2, text="Стартовое положение доп. оси, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r2, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_sp2 = tk.StringVar(value=values.get("start_ext_position_2", ""))
    tk.Entry(entry_frame_2, textvariable=var_sp2, width=15, font=("Arial", 10)).grid(
        row=r2, column=1, sticky="w", pady=PAD_Y)
    entries["start_ext_position_2"] = (var_sp2, "int")
    r2 += 1
    
    tk.Label(entry_frame_2, text="Положение для разворота к кантователю, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r2, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_rp2 = tk.StringVar(value=values.get("reverse_ext_position_2", ""))
    tk.Entry(entry_frame_2, textvariable=var_rp2, width=15, font=("Arial", 10)).grid(
        row=r2, column=1, sticky="w", pady=PAD_Y)
    entries["reverse_ext_position_2"] = (var_rp2, "int")
    
    # ============================================================
    # === 3. Общие параметры ===
    # ============================================================
    common_frame = LabelFrame(main_frame, text=" Общие параметры ", padx=FRAME_PAD, pady=FRAME_PAD)
    common_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
    common_frame.columnconfigure(1, weight=1)
    row += 1
    
    r3 = 0
    tk.Label(common_frame, text="Значение смещения, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r3, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_bounce = tk.StringVar(value=values.get("bounce_after_reverse", ""))
    tk.Entry(common_frame, textvariable=var_bounce, width=15, font=("Arial", 10)).grid(
        row=r3, column=1, sticky="w", pady=PAD_Y)
    entries["bounce_after_reverse"] = (var_bounce, "int")
    r3 += 1
    
    tk.Label(common_frame, text="Мин. диаметр окружности, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r3, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_min_d = tk.StringVar(value=values.get("min_diameter", "0"))
    tk.Entry(common_frame, textvariable=var_min_d, width=15, font=("Arial", 10)).grid(
        row=r3, column=1, sticky="w", pady=PAD_Y)
    entries["min_diameter"] = (var_min_d, "int")
    r3 += 1

    tk.Label(common_frame, text="Дополнительное смещение СК по X, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r3, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_DXF_offset_X = tk.StringVar(value=values.get("DXF_offset_X", ""))
    tk.Entry(common_frame, textvariable=var_DXF_offset_X, width=15, font=("Arial", 10)).grid(
        row=r3, column=1, sticky="w", pady=PAD_Y)
    entries["DXF_offset_X"] = (var_DXF_offset_X, "float")
    r3 += 1

    tk.Label(common_frame, text="Дополнительное смещение СК по Y, мм:",
             anchor="w", font=("Arial", 9)).grid(row=r3, column=0, sticky="w", padx=(0, 10), pady=PAD_Y)
    var_DXF_offset_Y = tk.StringVar(value=values.get("DXF_offset_Y", ""))
    tk.Entry(common_frame, textvariable=var_DXF_offset_Y, width=15, font=("Arial", 10)).grid(
        row=r3, column=1, sticky="w", pady=PAD_Y)
    entries["DXF_offset_Y"] = (var_DXF_offset_Y, "float")

    # ============================================================
    # === 4. Путь к файлу ===
    # ============================================================
    path_frame = LabelFrame(main_frame, text=" Исходный CNC/DXF-файл ", padx=FRAME_PAD, pady=FRAME_PAD)
    path_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
    path_frame.columnconfigure(0, weight=1)
    row += 1
    
    path_var = tk.StringVar(value=values.get("Source_CNC_DXF_Path", ""))

    path_entry = tk.Text(path_frame, height=3, width=40, font=("Arial", 9), wrap="word")
    path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=PAD_Y)
    path_entry.delete("1.0", "end")      # очистить
    path_entry.insert("1.0", path_var.get().strip())  # вставить в начало
    #path_entry = tk.Entry(path_frame, textvariable=path_var, font=("Arial", 9))
    #path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), pady=PAD_Y)
    
    def browse():
        initial_dir = ""
        current_path = path_entry.get("1.0", "end-1c").strip()
        if current_path and os.path.isdir(os.path.dirname(current_path)):
            initial_dir = os.path.dirname(current_path)
        elif SCRIPT_DIR:
            initial_dir = SCRIPT_DIR
        
        file_path = filedialog.askopenfilename(
            parent=root,
            title="Выберите исходный DXF-файл",
            initialdir=initial_dir,
            filetypes=[
                ("CNC файлы", "*.CNC"),
                ("DXF файлы", "*.dxf")
            ]
        )
        if file_path:
            path_entry.delete("1.0", "end")      # очистить
            path_entry.insert("1.0", file_path)  # вставить в начало
    
    tk.Button(path_frame, text="Обзор...", command=browse, width=12, font=("Arial", 9)).grid(
        row=0, column=1, sticky="e", pady=PAD_Y)
    
    # ============================================================
    # === 5. Кнопки ===
    # ============================================================
    btn_frame = tk.Frame(main_frame)
    btn_frame.grid(row=row, column=0, pady=(5, 0))
    row += 1
    
    result = {"ok": False, "values": None, "source_path": None, "lines": lines, "key_to_line": key_to_line}
    
    def on_calculate():
        new_values = {"machine": machine_var.get()}
        #new_values = {"DXF_offset_X": float(1000.0)}
        #new_values = {"DXF_offset_Y": float(0.0)}
        
        for key, (var, typ) in entries.items():
            raw = var.get().strip()
            try:
                if typ == "int":
                    new_values[key] = int(raw)
                elif typ == "float":
                    new_values[key] = float(raw)
                else:
                    new_values[key] = raw
            except ValueError:
                messagebox.showerror("Ошибка", f"Неверное значение для параметра '{key}': '{raw}'", parent=root)
                return

        file_path = path_entry.get("1.0", "end-1c").strip()
        
        if not file_path:
            messagebox.showerror("Ошибка", "Не указан путь к DXF-файлу.\nНажмите 'Обзор...' для выбора.", parent=root)
            return
        if not os.path.isfile(file_path):
            messagebox.showerror(
                "Ошибка",
                f"По указанному пути нет файла:\n{file_path}",
                parent=root
            )
            return
        
        new_values["Source_CNC_DXF_Path"] = file_path
        
        result["ok"] = True
        result["values"] = new_values
        result["source_path"] = file_path
        root.destroy()
    
    def on_exit():
        root.destroy()
    
    tk.Button(btn_frame, text="Рассчитать", width=15, font=("Arial", 10, "bold"),
              command=on_calculate, bg="#e0f0e0").pack(side="left", padx=10)
    tk.Button(btn_frame, text="Выход", width=15, font=("Arial", 10),
              command=on_exit).pack(side="left", padx=10)
    
    # Инициализация вида при старте
    update_plasma_view()
    
    # Центрируем окно
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"+{x}+{y}")
    
    root.protocol("WM_DELETE_WINDOW", on_exit)
    root.mainloop()
    
    if result["ok"]:
        save_config(CFG_PATH, result["lines"], result["key_to_line"], result["values"])
        return result["values"], result["source_path"]
    return None, None

def extract_and_save_circles_to_rapid(dxf_input_path, txt_output_path, settings, source_type):
    """
    Читает DXF файл, рассчитывает динамическое смещение внешней оси по координате Y
    и сохраняет результат в формате ABB RAPID robtarget с учетом выбранной машины.
    """
    # Загружаем настройки
    machine = int(settings.get("machine"))
    
    if machine == 1:
        start_ext = int(settings.get("start_ext_position_1"))
        reverse_limit = int(settings.get("reverse_ext_position_1"))
        bounce = int(settings.get("bounce_after_reverse"))
        sign = -1
        orient_str = "1,0,0,0"  # Кватернион для первой плазмы
    elif machine == 2:
        start_ext = int(settings.get("start_ext_position_2"))
        reverse_limit = int(settings.get("reverse_ext_position_2"))
        bounce = int(settings.get("bounce_after_reverse"))
        sign = 1
        orient_str = "0,1,0,0"  # Кватернион для второй плазмы
    else:
        print(f"Ошибка в указании номера плазмы. Должно быть 1 или 2")
        sys.exit(0)

    print("Загружены настройки:")
    print(f"machine = {machine}")
    print(f"start_ext = {start_ext}")
    print(f"reverse_limit = {reverse_limit}")
    print(f"bounce = {bounce}")
    print(f"sign = {sign}")
    print(f"orient = [{orient_str}]")
    print("")
    
    try:
        # 1. Загружаем документ DXF
        doc = ezdxf.readfile(str(dxf_input_path))
        msp = doc.modelspace()
        
        centers = []
        
        # 2. Извлекаем окружности
        for entity in msp:
            if entity.dxftype() == 'CIRCLE':
                cx, cy, cz = entity.dxf.center
                if source_type == "cnc":
                    centers.append((cx, cy))
                elif source_type == "dxf":
                    centers.append(((0-sign)*cy, cx))
                
        count = len(centers)
        
        if count == 0:
            print("Предупреждение: Окружности не найдены в файле.")
            return 0

            
        # 3. Записываем данные с вычислением шага внешней оси
        reverse_triggered = False
        first_y = None
        
        with open(txt_output_path, mode='w', encoding='utf-8') as txtfile:

            line = (f"!Начальное положение дополнительной оси: {start_ext}\n")
            txtfile.write(line)
            line = (f"!Положение дополнительной оси при котором совершён отскок: {reverse_limit}\n")
            txtfile.write(line)
            line = (f"!Величина отскока: {bounce}\n")
            txtfile.write(line)
            line = (f"!Дополнительное смещение СК X: {float(settings.get("DXF_offset_X"))}, Y: {float(settings.get("DXF_offset_Y"))}\n")
            txtfile.write(line)

            for index, (x, y) in enumerate(centers, start=1):
                
                if index == 1:
                    first_y = y
                    current_ext = start_ext
                else:
                    diff_from_first = y - first_y
                    current_ext = start_ext + sign * diff_from_first
                    
                    if not reverse_triggered:
                        if machine == 1 and current_ext <= reverse_limit:
                            reverse_triggered = True
                            print(f"reverse_triggered сработал на диске №{index}")
                        if machine == 2 and current_ext >= reverse_limit:
                            reverse_triggered = True
                            print(f"reverse_triggered сработал на диске №{index}")
                    
                    if reverse_triggered:
                        current_ext = current_ext - sign * bounce
                
                # Форматируем вывод
                y_str = f"{y:.2f}"
                x_str = f"{x:.2f}"
                ext_str = f"{current_ext:.2f}"
                
                # Шаблон строки для RAPID с подставленным кватернионом машины
                line = (
                    f"CONST robtarget Disk_{index}:="
                    f"[[{x_str},{y_str},0]"
                    f",[{orient_str}],[0,0,0,0],"
                    f"[{ext_str},9E+09,9E+09,9E+09,9E+09,9E+09]];\n"
                )
                txtfile.write(line)
     
        return count

    except FileNotFoundError:
        print(f"Ошибка: Файл {dxf_input_path} не найден.", file=sys.stderr)
        return -1
    except Exception as e:
        print(f"Произошла ошибка при обработке файла: {e}", file=sys.stderr)
        return -1

def prepare_dxf(SRC, DST, MIN_DIAMETER):
    """Делает подготовку файла dxf для дальнейшей переработки. Сращивает дуги в одну окружность, удаляет концентричные окружности кроме минимальной и удаляет все окружности меньшего диамтера чем MIN_DIAMETER
    * SRC - Файл источник
    * DST - Сохраняемый файл после перерботки
    * MIN_DIAMETER - порог для удаления окружностей меньшего размера
    """
    print(f"Исходный файл: {SRC}")
    print(f"Выходной файл: {DST}")
    print(f"Минимальный диаметр окружности: {MIN_DIAMETER} мм")

    # Точность 1 мм — используется только на этапе фильтрации
    def r1mm(v):
        return int(round(v)) if v is not None else None

    # === Чтение и базовый парсинг DXF ===
    raw = open(SRC, "rb").read()
    text = raw.decode("cp1251")
    assert "\r\n" in text
    lines = text.split("\r\n")
    assert lines[-1] == ""
    toks = [(lines[i], lines[i+1]) for i in range(0, len(lines) - 1, 2)]

    def strip(t): return (t[0].strip(), t[1].strip())

    # Поиск секции ENTITIES
    i_sec = None
    for i in range(len(toks) - 1):
        if strip(toks[i]) == ("0", "SECTION") and strip(toks[i+1]) == ("2", "ENTITIES"):
            i_sec = i + 2
            break
    assert i_sec is not None

    i_end = None
    for j in range(i_sec, len(toks)):
        if strip(toks[j]) == ("0", "ENDSEC"):
            i_end = j
            break
    assert i_end is not None

    prefix = toks[:i_sec]
    body = toks[i_sec:i_end]
    suffix = toks[i_end:]

    # Разбор на сущности
    entities = []
    cur = []
    for t in body:
        if strip(t)[0] == "0":
            if cur:
                entities.append(cur)
            cur = [t]
        else:
            cur.append(t)
    if cur:
        entities.append(cur)

    print(f"Исходное количество сущностей: {len(entities)}")

    # Вспомогательные функции
    def get(e, code):
        for c, v in e[1:]:
            if int(c) == code:
                return v
        return None

    def fget(e, code):
        v = get(e, code)
        return float(v) if v is not None else None

    def arcs_form_circle(arcs):
        """Проверяет, покрывают ли дуги полные 360 градусов."""
        intervals = []
        for a in arcs:
            start = fget(a, 50)
            end = fget(a, 51)
            if start is None or end is None:
                return False
            
            start = start % 360.0
            end = end % 360.0
            
            if abs(start - end) < 1e-4:
                return True
                
            if start < end:
                intervals.append((start, end))
            else:
                intervals.append((start, 360.0))
                intervals.append((0.0, end))

        intervals.sort(key=lambda x: x[0])
        merged = []
        for s, e in intervals:
            if not merged:
                merged.append([s, e])
            else:
                if s <= merged[-1][1] + 1e-4:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])

        if merged and merged[0][0] <= 1e-4 and merged[-1][1] >= 360.0 - 1e-4:
            for i in range(len(merged) - 1):
                if merged[i][1] < merged[i+1][0] - 1e-4:
                    return False
            return True
        return False

    # === Группировка дуг и создание окружностей ===
    arc_groups = {}
    for e in entities:
        if strip(e[0])[1] == "ARC":
            layer = get(e, 8) or "0"
            color = get(e, 62) or "256"
            cx = round(fget(e, 10), 5)
            cy = round(fget(e, 20), 5)
            r = round(fget(e, 40), 2)
            key = (layer, color, cx, cy, r)
            if key not in arc_groups:
                arc_groups[key] = []
            arc_groups[key].append(e)

    new_circles = []
    consumed_arcs = set()

    for key, arcs in arc_groups.items():
        if arcs_form_circle(arcs):
            layer, color, cx, cy, r = key
            avg_cx = sum(fget(a, 10) for a in arcs) / len(arcs)
            avg_cy = sum(fget(a, 20) for a in arcs) / len(arcs)
            avg_r  = sum(fget(a, 40) for a in arcs) / len(arcs)
            z = get(arcs[0], 30) or "0.0"
            
            circ = [
                ("0", "CIRCLE"),
                ("8", "0"),
                ("10", str(avg_cx)),
                ("20", str(avg_cy)),
                ("30", z),
                ("40", str(avg_r)),
            ]
            new_circles.append(circ)
            for a in arcs:
                consumed_arcs.add(id(a))

    print(f"Найдено групп дуг, образующих круг: {len(new_circles)}")

    # Формируем промежуточный список
    intermediate = []
    for e in entities:
        if id(e) not in consumed_arcs:
            intermediate.append(e)
    intermediate.extend(new_circles)

    # === Фильтрация окружностей ===
    circles = []
    non_circles = []
    for e in intermediate:
        if strip(e[0])[1] == "CIRCLE":
            circles.append(e)
        else:
            non_circles.append(e)

    # Удаление дубликатов
    seen_circles = set()
    unique_circles = []
    for c in circles:
        cx = r1mm(fget(c, 10))
        cy = r1mm(fget(c, 20))
        r = r1mm(fget(c, 40))
        key = (cx, cy, r)
        if key not in seen_circles:
            seen_circles.add(key)
            unique_circles.append(c)

    print(f"Удалено дубликатов окружностей: {len(circles) - len(unique_circles)}")

    # Удаление концентрических окружностей
    concentric_groups = {}
    for c in unique_circles:
        cx = r1mm(fget(c, 10))
        cy = r1mm(fget(c, 20))
        key = (cx, cy)
        if key not in concentric_groups:
            concentric_groups[key] = []
        concentric_groups[key].append(c)

    after_concentric = []
    removed_concentric = 0
    for key, group in concentric_groups.items():
        min_r = min(fget(c, 40) for c in group)
        for c in group:
            if abs(fget(c, 40) - min_r) < 1.0:
                after_concentric.append(c)
            else:
                removed_concentric += 1

    print(f"Удалено концентрических окружностей (с радиусом > минимального): {removed_concentric}")

    # Удаление окружностей с диаметром меньше min_diameter
    final_circles = []
    removed_by_diameter = 0
    for c in after_concentric:
        r = fget(c, 40)
        if r is not None and (2 * r) < MIN_DIAMETER:
            removed_by_diameter += 1
        else:
            final_circles.append(c)

    print(f"Удалено окружностей с диаметром < {MIN_DIAMETER} мм: {removed_by_diameter}")

    # === Сборка итогового файла ===
    out_entities = non_circles + final_circles
    print(f"Итоговое количество сущностей: {len(out_entities)}")

    out_toks = list(prefix)
    for e in out_entities:
        out_toks.extend(e)
    out_toks.extend(suffix)

    lines_out = []
    for code, val in out_toks:
        lines_out.append(code)
        lines_out.append(val)
    out_text = "\r\n".join(lines_out) + "\r\n"

    open(DST, "wb").write(out_text.encode("cp1251"))
    print(f"\nФайл успешно записан: {DST}")
    print(f"Размер: {len(out_text.encode('cp1251'))} байт")

def main():
        # === Запуск окна настроек ===
    try:
        settings, SRC = show_settings_window()
    except FileNotFoundError as e:
        print(f"Ошибка: {e}")
        sys.exit(1)

    if settings is None or SRC is None:
        print("Работа прервана пользователем.")
        sys.exit(0)

    # Формируем путь к выходному файлу
    base_name = os.path.splitext(os.path.basename(SRC))[0]
    extension = os.path.splitext(os.path.basename(SRC))[1][1:].lower()
    DST = os.path.join(SCRIPT_DIR , ".dxf", base_name + "_circles.dxf")
    MIN_DIAMETER = int(settings.get("min_diameter", 0))
    OFFSET_X = float(settings.get("DXF_offset_X", 0.0))
    OFFSRT_Y = float(settings.get("DXF_offset_Y", 0.0))

    if(extension=="dxf"):
        prepare_dxf(SRC, DST, MIN_DIAMETER)
    elif(extension == "cnc"):
        DST_CNC = os.path.join(SCRIPT_DIR , ".dxf", base_name + "_from_cnc.dxf")
        prepare_cnc.cnc_to_dxf(SRC, DST_CNC, OFFSET_X, OFFSRT_Y)
        prepare_dxf(DST_CNC, DST, MIN_DIAMETER)
    else:
        print(f"Файлы типа '{extension}' не поддерживаются, выберите файл типа dxf или cnc")
        sys.exit(0)

    print(f"Чтение DXF файла: {DST}...")

    path_out = Path(output_txt_file)
    num_circles = extract_and_save_circles_to_rapid(DST, path_out, settings, extension)
    
    if num_circles > 0:
        print(f"Успешно! Найдено и сохранено {num_circles} точек в формате RAPID.")
        print(f"Результат записан в файл: {output_txt_file}")
    elif num_circles == 0:
        print("Обработка завершена, но окружности не были найдены.")
    else:
        print("Обработка завершилась с ошибкой.")

if __name__ == "__main__":
    main()
