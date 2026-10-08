import subprocess
import tempfile
import threading
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A3, A4, LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import config


PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".odt", ".odp", ".ods"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | OFFICE_EXTENSIONS | IMAGE_EXTENSIONS

PAGE_SIZES = {"a4": A4, "a3": A3, "letter": LETTER}

# Image margin on the printed page (points; 18pt = 1/4 inch)
IMAGE_MARGIN = 18

# LibreOffice can only run one conversion per profile at a time
_libreoffice_lock = threading.Lock()

# PDFium is not thread-safe, and FastAPI runs requests on several threads
_pdfium_lock = threading.Lock()

# Preview image widths in pixels
PREVIEW_WIDTHS = {"small": 260, "large": 1000}


class DocumentError(Exception):
    """A problem with the user's document that should be reported to them."""


def file_kind(extension):
    if extension in PDF_EXTENSIONS:
        return "pdf"
    if extension in OFFICE_EXTENSIONS:
        return "office"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    return None


def count_pages(pdf_path):
    with _pdfium_lock:
        try:
            document = pdfium.PdfDocument(str(pdf_path))
        except pdfium.PdfiumError as error:
            raise DocumentError(
                "The PDF could not be read. It may be damaged or password protected."
            ) from error

        try:
            pages = len(document)
        finally:
            document.close()

    if pages < 1:
        raise DocumentError("The document has no pages.")

    return pages


def render_preview(pdf_path, page_index, size, cache_dir):
    """JPEG preview of one page, cached next to the upload. Returns its path."""

    cached = Path(cache_dir) / f"preview-{size}-{page_index}.jpg"
    if cached.exists():
        return cached

    width = PREVIEW_WIDTHS[size]

    with _pdfium_lock:
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            if not 0 <= page_index < len(document):
                raise IndexError(page_index)
            page = document[page_index]
            try:
                page_width = page.get_width()
                image = page.render(scale=width / page_width).to_pil()
            finally:
                page.close()
        finally:
            document.close()

    image.convert("RGB").save(cached, "JPEG", quality=85, optimize=True)
    return cached


def convert_to_pdf(file_path):
    """Convert an office document to PDF with LibreOffice."""

    file_path = Path(file_path)

    # Checked on every call, since LibreOffice may be installed or removed while running
    if not config.LIBREOFFICE_PATH or not Path(config.LIBREOFFICE_PATH).exists():
        config.LIBREOFFICE_PATH = config.find_libreoffice()

    if not config.LIBREOFFICE_PATH:
        raise DocumentError(
            "Office documents cannot be converted on this server "
            "(LibreOffice is not installed). Please upload a PDF."
        )

    # A private profile lets conversion work even while the user has
    # LibreOffice open, which otherwise makes --headless silently do nothing.
    profile_dir = Path(tempfile.gettempdir()) / "printify-libreoffice"

    with _libreoffice_lock:
        try:
            subprocess.run(
                [
                    config.LIBREOFFICE_PATH,
                    f"-env:UserInstallation={profile_dir.as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(file_path.parent),
                    str(file_path),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise DocumentError("The document could not be converted to PDF.") from error

    pdf_path = file_path.with_suffix(".pdf")

    if not pdf_path.exists():
        raise DocumentError("The document could not be converted to PDF.")

    return pdf_path


def _load_rgb_image(image_path):
    with Image.open(image_path) as original:

        # Correct phone-camera orientation
        image = ImageOps.exif_transpose(original)

        if image.mode == "P":
            image = image.convert("RGBA")

        # Put transparent images on a white background
        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            return background

        return image.convert("RGB")


def image_to_pdf(image_path, paper_size, pdf_path=None):
    """Place an image on a single page, scaled to fit and centred."""

    image_path = Path(image_path)
    page_size = PAGE_SIZES.get(paper_size.lower(), A4)
    pdf_path = Path(pdf_path) if pdf_path else image_path.with_suffix(".pdf")

    image = _load_rgb_image(image_path)

    page_width, page_height = page_size
    image_width, image_height = image.size

    # Turn the page sideways for landscape pictures
    if image_width > image_height:
        page_width, page_height = page_height, page_width

    usable_width = page_width - 2 * IMAGE_MARGIN
    usable_height = page_height - 2 * IMAGE_MARGIN

    scale = min(usable_width / image_width, usable_height / image_height)

    new_width = image_width * scale
    new_height = image_height * scale

    x = (page_width - new_width) / 2
    y = (page_height - new_height) / 2

    pdf = canvas.Canvas(str(pdf_path), pagesize=(page_width, page_height))
    pdf.drawImage(ImageReader(image), x, y, width=new_width, height=new_height)
    pdf.showPage()
    pdf.save()

    return pdf_path


def verify_image(image_path):
    try:
        with Image.open(image_path) as image:
            image.verify()
    except Exception as error:
        raise DocumentError("The image file is damaged or not a real image.") from error


def prepare_document(source_path, kind, paper_size="a4"):
    """Turn an uploaded file into a printable PDF. Returns (pdf_path, pages)."""

    source_path = Path(source_path)

    if kind == "pdf":
        pdf_path = source_path

    elif kind == "office":
        pdf_path = convert_to_pdf(source_path)

    elif kind == "image":
        verify_image(source_path)
        pdf_path = image_to_pdf(source_path, paper_size, source_path.with_name("document.pdf"))

    else:
        raise DocumentError("This file type is not supported.")

    return pdf_path, count_pages(pdf_path)
