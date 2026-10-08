import win32print

printer_name = "EPSON3FD768 (L4360 Series)"

# Open the printer
printer = win32print.OpenPrinter(printer_name)

# Get printer information
info = win32print.GetPrinter(printer, 2)

print("Printer connected successfully!")
print("Printer name:", info["pPrinterName"])
print("Status:", info["Status"])

# Close the printer
win32print.ClosePrinter(printer)