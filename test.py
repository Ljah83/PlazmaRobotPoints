import main

SRC = "e:\разно\Работа\БЗТДиА\Цех колёс\dxf_coord_read\settings.cfg"
values, lines, key_to_line = main.read_config(SRC)

for i in values:
    print(values[i])