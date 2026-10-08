import os
import time
import win32print

printer_name = "EPSON3FD768 (L4360 Series)"
pdf_path = os.path.abspath("test.pdf")


if not os.path.exists(pdf_path):
    print("PDF file not found!")
    print("Expected:", pdf_path)
    exit()


win32print.SetDefaultPrinter(printer_name)

print("Printer:", printer_name)
print("PDF:", pdf_path)


os.startfile(pdf_path, "print")

print("PDF print command sent!")


time.sleep(5)
print("Done.")