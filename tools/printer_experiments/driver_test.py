import win32print
import os
import time

printer_name = "EPSON3FD768 (L4360 Series)"

win32print.SetDefaultPrinter(printer_name)

print("Default printer set to:", printer_name)


file_path = os.path.abspath("python_test.txt")
with open(file_path, "w", encoding="utf-8") as file:
    file.write(
        "ONLINE PRINTING PROJECT\n\n"
        "This page was sent using Python\n"
        "through the Windows printer driver.\n\n"
        "Printer: EPSON L4360\n"
    )

print("Test file created.")

os.startfile(file_path, "print")

print("Print command sent to Windows.")

time.sleep(5)