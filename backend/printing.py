"""Windows printing: printer status and printing PDFs with the chosen options.

PDF pages are rendered with PDFium and drawn onto a Windows printer device
context, so no external PDF viewer is needed and the colour, paper size and
duplex settings are applied through the printer driver.
"""

import threading
import time

import pypdfium2 as pdfium
from PIL import ImageWin

try:
    import pywintypes
    import win32con
    import win32gui
    import win32print
    WINDOWS_PRINTING = True
except ImportError:  # not on Windows / pywin32 missing
    WINDOWS_PRINTING = False


# Windows paper size codes (DMPAPER_*)
PAPER_CODES = {"letter": 1, "a3": 8, "a4": 9}

DMCOLOR_MONOCHROME = 1
DMCOLOR_COLOR = 2
DMDUP_SIMPLEX = 1
DMDUP_VERTICAL = 2  # flip on long edge

# Highest resolution pages are rendered at before being sent to the driver
MAX_RENDER_DPI = 300

PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400

PRINTER_STATUS_MESSAGES = {
    0x00000002: "Printer error",
    0x00000008: "Paper jam",
    0x00000010: "Out of paper",
    0x00000080: "Printer is offline",
    0x00000400: "Printer is busy",
    0x00020000: "Toner/ink is low",
    0x00040000: "Out of ink",
    0x00100000: "Printer needs attention",
    0x00400000: "Printer door is open",
}

JOB_PROBLEM_MESSAGES = {
    0x00000002: "Print job error",
    0x00000020: "Printer is offline",
    0x00000040: "Printer is out of paper",
    0x00000200: "Printer needs attention",
    0x00000400: "Printer is blocked by a problem",
}

JOB_STATUS_DELETED = 0x00000100 | 0x00000004  # deleted / deleting


class PrintError(Exception):
    pass


def default_printer():
    if not WINDOWS_PRINTING:
        return None
    try:
        return win32print.GetDefaultPrinter()
    except pywintypes.error:
        return None


# Printer drivers are not safe to query from several threads at once (the
# server answers requests in parallel), so status checks take turns and a
# recent answer is reused instead of asking the driver again.
_printer_lock = threading.Lock()
_printer_cache = {}
PRINTER_INFO_MAX_AGE = 3  # seconds


def printer_info(printer_name=None):
    """Status and capabilities of a printer, for the website and admin page."""

    with _printer_lock:
        cached = _printer_cache.get(printer_name)
        if cached and time.monotonic() - cached[0] < PRINTER_INFO_MAX_AGE:
            return dict(cached[1])

        info = _read_printer_info(printer_name)
        _printer_cache[printer_name] = (time.monotonic(), info)
        return dict(info)


def _read_printer_info(printer_name):
    printer_name = printer_name or default_printer()

    if not WINDOWS_PRINTING or not printer_name:
        return {
            "available": False,
            "name": printer_name,
            "ready": False,
            "message": "No printer configured",
            "papers": list(PAPER_CODES),
            "duplex": True,
            "color": True,
            "jobs": 0,
        }

    try:
        handle = win32print.OpenPrinter(printer_name)
        try:
            info = win32print.GetPrinter(handle, 2)
        finally:
            win32print.ClosePrinter(handle)
    except pywintypes.error:
        return {
            "available": False,
            "name": printer_name,
            "ready": False,
            "message": "Printer not found",
            "papers": list(PAPER_CODES),
            "duplex": True,
            "color": True,
            "jobs": 0,
        }

    port = info["pPortName"]

    def capability(code):
        try:
            return win32print.DeviceCapabilities(printer_name, port, code)
        except pywintypes.error:
            return None

    paper_codes = capability(win32con.DC_PAPERS) or PAPER_CODES.values()
    papers = [name for name, code in PAPER_CODES.items() if code in paper_codes]

    problems = [
        message
        for flag, message in PRINTER_STATUS_MESSAGES.items()
        if info["Status"] & flag
    ]
    if info["Attributes"] & PRINTER_ATTRIBUTE_WORK_OFFLINE:
        problems.append("Printer is offline")

    # "Busy" and "ink low" do not stop printing
    blocking = [p for p in problems if p not in ("Printer is busy", "Toner/ink is low")]

    return {
        "available": True,
        "name": printer_name,
        "ready": not blocking,
        "message": ", ".join(problems) if problems else "Printer ready",
        "papers": papers,
        "duplex": capability(win32con.DC_DUPLEX) == 1,
        "color": capability(win32con.DC_COLORDEVICE) != 0,
        "jobs": info["cJobs"],
    }


def _page_sequence(page_count, copies, duplex):
    """Page indexes for all copies; None means a blank page.

    With double-sided printing each copy must start on a new sheet, so an
    odd-length document gets a blank back page between copies.
    """

    one_copy = list(range(page_count))
    if duplex and page_count % 2 == 1 and copies > 1:
        one_copy.append(None)

    sequence = one_copy * copies

    # No need to feed a blank sheet side at the very end
    while sequence and sequence[-1] is None:
        sequence.pop()

    return sequence


def _printer_devmode(handle, printer_name, color, paper, duplex):
    devmode = win32print.GetPrinter(handle, 2)["pDevMode"]
    if devmode is None:
        devmode = win32print.DocumentProperties(0, handle, printer_name, None, None, 0)

    devmode.PaperSize = PAPER_CODES[paper]
    devmode.Orientation = win32con.DMORIENT_PORTRAIT
    devmode.Color = DMCOLOR_COLOR if color == "color" else DMCOLOR_MONOCHROME
    devmode.Duplex = DMDUP_VERTICAL if duplex else DMDUP_SIMPLEX
    devmode.Copies = 1  # copies are sent as separate pages
    devmode.Fields |= (
        win32con.DM_PAPERSIZE
        | win32con.DM_ORIENTATION
        | win32con.DM_COLOR
        | win32con.DM_DUPLEX
        | win32con.DM_COPIES
    )

    # Let the driver merge in and validate our settings
    win32print.DocumentProperties(
        0, handle, printer_name, devmode, devmode,
        win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER,
    )
    return devmode


def print_pdf(
    pdf_path,
    printer_name=None,
    *,
    color="bw",
    copies=1,
    paper="a4",
    duplex=False,
    document_name="Printify order",
    output_file=None,
):
    """Send a PDF to the printer. Returns the Windows print job id.

    output_file is passed to the spooler, which lets "Microsoft Print to PDF"
    write straight to a file (used by the tests).
    """

    if not WINDOWS_PRINTING:
        raise PrintError("Printing is only supported on Windows with pywin32 installed")

    printer_name = printer_name or default_printer()
    if not printer_name:
        raise PrintError("No printer configured")

    try:
        document = pdfium.PdfDocument(str(pdf_path))
    except pdfium.PdfiumError as error:
        raise PrintError(f"Could not open the PDF: {error}") from error

    try:
        handle = win32print.OpenPrinter(printer_name)
    except pywintypes.error as error:
        document.close()
        raise PrintError(f"Printer not found: {printer_name}") from error

    hdc = None
    try:
        devmode = _printer_devmode(handle, printer_name, color, paper, duplex)

        hdc = win32gui.CreateDC("WINSPOOL", printer_name, devmode)

        printable_width = win32print.GetDeviceCaps(hdc, win32con.HORZRES)
        printable_height = win32print.GetDeviceCaps(hdc, win32con.VERTRES)
        dpi = win32print.GetDeviceCaps(hdc, win32con.LOGPIXELSX)

        # Printable area in points, so PDF pages can be scaled to it
        points_per_pixel = 72 / dpi
        area_width = printable_width * points_per_pixel
        area_height = printable_height * points_per_pixel

        job_id = win32print.StartDoc(
            hdc, (document_name, str(output_file) if output_file else None, None, 0)
        )

        try:
            for index in _page_sequence(len(document), copies, duplex):
                win32print.StartPage(hdc)
                if index is not None:
                    page = document[index]
                    try:
                        _draw_scaled(hdc, page, color, area_width, area_height, dpi)
                    finally:
                        page.close()
                win32print.EndPage(hdc)
        except Exception:
            win32print.AbortDoc(hdc)
            raise

        win32print.EndDoc(hdc)
        return job_id

    except pywintypes.error as error:
        raise PrintError(f"Printer error: {error.strerror}") from error

    finally:
        if hdc is not None:
            win32gui.DeleteDC(hdc)
        win32print.ClosePrinter(handle)
        document.close()

def _draw_scaled(hdc, page, color, area_width_pt, area_height_pt, dpi):
    """Draw a page scaled to fit the printable area (given in points)."""

    width_pt, height_pt = page.get_size()

    # Rotate landscape pages to fill the portrait sheet
    rotate = width_pt > height_pt
    if rotate:
        width_pt, height_pt = height_pt, width_pt

    fit = min(area_width_pt / width_pt, area_height_pt / height_pt)

    # Render at printer resolution, capped to keep memory reasonable
    render_dpi = min(dpi, MAX_RENDER_DPI)
    image = page.render(
        scale=fit * render_dpi / 72,
        rotation=270 if rotate else 0,  # counter-clockwise, like Windows landscape
        grayscale=(color != "color"),
    ).to_pil()
    image = image.convert("RGB" if color == "color" else "L")

    pixels_per_point = dpi / 72
    target_width = int(width_pt * fit * pixels_per_point)
    target_height = int(height_pt * fit * pixels_per_point)
    left = (int(area_width_pt * pixels_per_point) - target_width) // 2
    top = (int(area_height_pt * pixels_per_point) - target_height) // 2

    ImageWin.Dib(image).draw(
        hdc,
        (left, top, left + target_width, top + target_height),
    )


def wait_for_job(printer_name, job_id, on_problem=None, timeout=900, poll=2):
    """Wait until the spooler has finished a job.

    Returns True when the job left the queue, False on timeout.
    on_problem(message or None) is called whenever the job's problem changes,
    e.g. the printer runs out of paper.
    """

    if not WINDOWS_PRINTING:
        return True

    handle = win32print.OpenPrinter(printer_name)
    last_problem = None
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            try:
                job = win32print.GetJob(handle, job_id, 1)
            except pywintypes.error:
                return True  # job no longer in the queue: it has printed

            status = job["Status"]
            if status & JOB_STATUS_DELETED:
                return True

            problem = next(
                (message for flag, message in JOB_PROBLEM_MESSAGES.items() if status & flag),
                None,
            )
            if problem != last_problem and on_problem:
                on_problem(problem)
            last_problem = problem

            time.sleep(poll)

        return False
    finally:
        win32print.ClosePrinter(handle)
