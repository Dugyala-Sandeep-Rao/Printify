import win32print

printer_name = "EPSON3FD768 (L4360 Series)"

printer = win32print.OpenPrinter(printer_name)

try:
    job = win32print.StartDocPrinter(
        printer,
        1,
        ("Online Printing Test", None, "RAW")
    )

    win32print.StartPagePrinter(printer)

    text = """
ONLINE PRINTING PROJECT

This is my first test print.
Python is connected to my Epson printer!

Printer: EPSON L4360
"""

    win32print.WritePrinter(printer, text.encode("utf-8"))

    win32print.EndPagePrinter(printer)
    win32print.EndDocPrinter(printer)

    print("Print job sent successfully!")

finally:
    win32print.ClosePrinter(printer)