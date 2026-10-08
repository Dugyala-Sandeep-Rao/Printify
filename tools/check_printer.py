"""Show installed printers and what Printify can use them for.

    python tools/check_printer.py
    python tools/check_printer.py --test-page "EPSON L4360 Series"
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import win32print  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

import printing  # noqa: E402


def make_test_page(path):
    pdf = canvas.Canvas(str(path))
    pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(72, 740, "Printify test page")
    pdf.setFont("Helvetica", 14)
    pdf.drawString(72, 700, "If you can read this, the print agent can use this printer.")
    pdf.rect(72, 72, 451, 600)
    pdf.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-page", metavar="PRINTER", help="print a one-page test on this printer")
    args = parser.parse_args()

    default = printing.default_printer()

    for printer in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS):
        name = printer[2]
        info = printing.printer_info(name)
        print(f"{'*' if name == default else ' '} {name}")
        print(f"    {info['message']} | papers: {', '.join(info['papers']) or '-'} | "
              f"duplex: {'yes' if info['duplex'] else 'no'} | colour: {'yes' if info['color'] else 'no'}")

    print("\n* = Windows default printer (used unless PRINTIFY_PRINTER is set)")

    if args.test_page:
        path = Path(tempfile.gettempdir()) / "printify-test-page.pdf"
        make_test_page(path)
        job = printing.print_pdf(path, args.test_page, document_name="Printify test page")
        print(f"\nTest page sent to {args.test_page} (job {job}).")


if __name__ == "__main__":
    main()
