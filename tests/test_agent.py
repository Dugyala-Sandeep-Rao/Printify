import sqlite3

import pytest

import agent
import config
import database
import printing
from conftest import make_pdf


def queued_order(client, uploaded_pdf, **options):
    body = {"upload_id": uploaded_pdf["upload_id"], **options}
    order = client.post("/api/orders", json=body).json()
    client.post(
        f"/api/orders/{order['order']['id']}/pay",
        json={"token": order["token"], "method": "upi"},
    )
    return order["order"]["id"]


def order_row(order_id):
    with database.connect() as connection:
        return connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def clear_queue():
    with database.connect() as connection:
        connection.execute("UPDATE orders SET status = 'cancelled' WHERE status = 'queued'")


def test_agent_prints_queued_order(client, uploaded_pdf, monkeypatch):
    clear_queue()
    order_id = queued_order(client, uploaded_pdf, color="color", copies=2, sides="double")

    calls = []

    def fake_print(pdf_path, printer_name, **options):
        calls.append((pdf_path, printer_name, options))
        return 7

    monkeypatch.setattr(printing, "print_pdf", fake_print)
    monkeypatch.setattr(printing, "wait_for_job", lambda *args, **kwargs: True)

    order = agent.claim_next_order()
    assert order["id"] == order_id
    assert order_row(order_id)["status"] == "printing"

    agent.process_order(order, "Test printer")

    assert len(calls) == 1
    _, printer_name, options = calls[0]
    assert printer_name == "Test printer"
    assert options["color"] == "color"
    assert options["copies"] == 2
    assert options["duplex"] is True

    row = order_row(order_id)
    assert row["status"] == "completed"
    assert row["printed_at"] is not None

    # The printed document is deleted straight away
    assert row["filename"] == "Deleted after printing"
    assert row["pdf_path"] is None
    assert not (config.UPLOAD_FOLDER / uploaded_pdf["upload_id"]).exists()


def test_failed_print_keeps_document_for_retry(client, uploaded_pdf, monkeypatch):
    clear_queue()
    order_id = queued_order(client, uploaded_pdf)

    def broken_print(*args, **kwargs):
        raise printing.PrintError("Out of paper")

    monkeypatch.setattr(printing, "print_pdf", broken_print)
    agent.process_order(agent.claim_next_order(), "Test printer")

    row = order_row(order_id)
    assert row["status"] == "failed"
    assert row["filename"] == "notes.pdf"
    assert (config.UPLOAD_FOLDER / uploaded_pdf["upload_id"]).exists()


def test_agent_marks_printer_errors(client, uploaded_pdf, monkeypatch):
    clear_queue()
    order_id = queued_order(client, uploaded_pdf)

    def broken_print(*args, **kwargs):
        raise printing.PrintError("Printer not found: Test printer")

    monkeypatch.setattr(printing, "print_pdf", broken_print)

    agent.process_order(agent.claim_next_order(), "Test printer")

    row = order_row(order_id)
    assert row["status"] == "failed"
    assert "Printer not found" in row["error"]


def test_agent_reports_printer_problems_while_waiting(client, uploaded_pdf, monkeypatch):
    clear_queue()
    order_id = queued_order(client, uploaded_pdf)

    def slow_printer(printer_name, job_id, on_problem=None, **kwargs):
        on_problem("Printer is out of paper")
        assert order_row(order_id)["error"] == "Printer is out of paper"
        return True

    monkeypatch.setattr(printing, "print_pdf", lambda *args, **kwargs: 1)
    monkeypatch.setattr(printing, "wait_for_job", slow_printer)

    agent.process_order(agent.claim_next_order(), "Test printer")

    row = order_row(order_id)
    assert row["status"] == "completed"
    assert row["error"] is None


def test_interrupted_orders_are_flagged(client, uploaded_pdf):
    clear_queue()
    order_id = queued_order(client, uploaded_pdf)
    agent.claim_next_order()

    agent.recover_interrupted_orders()

    assert order_row(order_id)["status"] == "failed"


def test_empty_queue(client):
    clear_queue()
    assert agent.claim_next_order() is None


def test_page_sequence_starts_each_duplex_copy_on_new_sheet():
    assert printing._page_sequence(3, 2, duplex=True) == [0, 1, 2, None, 0, 1, 2]
    assert printing._page_sequence(3, 2, duplex=False) == [0, 1, 2, 0, 1, 2]
    assert printing._page_sequence(2, 2, duplex=True) == [0, 1, 0, 1]
    assert printing._page_sequence(3, 1, duplex=True) == [0, 1, 2]


def test_old_database_is_upgraded(tmp_path, monkeypatch):
    old_db = tmp_path / "old.db"
    with sqlite3.connect(old_db) as connection:
        connection.execute("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
                pages INTEGER NOT NULL, color TEXT NOT NULL, copies INTEGER NOT NULL,
                paper TEXT NOT NULL, sides TEXT NOT NULL, total_price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute(
            "INSERT INTO orders (filename, pages, color, copies, paper, sides, total_price) "
            "VALUES ('old.pptx', 16, 'bw', 1, 'a4', 'single', 32)"
        )

    monkeypatch.setattr(config, "DATABASE_PATH", old_db)
    database.init_db()

    with database.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)")}
        count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        status = connection.execute("SELECT status FROM orders").fetchone()[0]

    assert set(database.ORDER_EXTRA_COLUMNS) <= columns
    assert count == 1
    assert status == "awaiting_payment"


PDF_PRINTER = "Microsoft Print to PDF"


def pdf_printer_installed():
    try:
        import win32print
        names = [p[2] for p in win32print.EnumPrinters(2)]
    except Exception:
        return False
    return PDF_PRINTER in names


@pytest.mark.skipif(not pdf_printer_installed(), reason="Microsoft Print to PDF not available")
def test_real_print_to_pdf_file(tmp_path):
    import pypdfium2 as pdfium

    source = make_pdf(tmp_path / "source.pdf", pages=3, landscape_last=True)
    output = tmp_path / "printed.pdf"

    job_id = printing.print_pdf(
        source, PDF_PRINTER, color="bw", copies=2, paper="a4", output_file=output
    )
    assert isinstance(job_id, int)
    assert printing.wait_for_job(PDF_PRINTER, job_id, timeout=120)

    document = pdfium.PdfDocument(str(output))
    try:
        assert len(document) == 6
        width, height = document[0].get_size()
        assert round(width) == 595 and round(height) == 842  # A4
    finally:
        document.close()


def test_old_uploads_are_deleted_unless_an_order_needs_them(client, uploaded_pdf, tmp_path):
    clear_queue()
    kept = queued_order(client, uploaded_pdf)  # queued order keeps its file

    unused = make_pdf(tmp_path / "unused.pdf", pages=1)
    with open(unused, "rb") as file:
        unused_id = client.post("/api/upload", files={"file": ("unused.pdf", file)}).json()["upload_id"]

    with database.connect() as connection:
        connection.execute("UPDATE uploads SET created_at = datetime('now', '-30 days')")

    agent.delete_old_uploads(keep_days=7)

    assert not (config.UPLOAD_FOLDER / unused_id).exists()
    assert (config.UPLOAD_FOLDER / uploaded_pdf["upload_id"]).exists()
    assert order_row(kept)["status"] == "queued"
