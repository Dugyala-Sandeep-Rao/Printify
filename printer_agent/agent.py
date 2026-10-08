"""Printify print agent.

Runs on the PC connected to the printer. It picks up paid orders from the
database, prints them with the customer's options and updates their status.

    python printer_agent/agent.py            # run continuously
    python printer_agent/agent.py --once     # print what is queued, then exit
    python printer_agent/agent.py --printer "Microsoft Print to PDF" --output-dir prints
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import config  # noqa: E402
import printing  # noqa: E402
from database import connect, forget_document, init_db, set_order_status  # noqa: E402


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def claim_next_order():
    """Atomically move the oldest queued order to 'printing'."""

    with connect() as connection:
        order = connection.execute(
            """
            SELECT * FROM orders
            WHERE status = 'queued'
            ORDER BY paid_at, id
            LIMIT 1
            """
        ).fetchone()

        if order is None:
            return None

        claimed = connection.execute(
            """
            UPDATE orders
            SET status = 'printing', error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'queued'
            """,
            (order["id"],),
        ).rowcount

    # Another agent (or a cancel) got there first
    return order if claimed else None


def update_order(order_id, status, **fields):
    with connect() as connection:
        set_order_status(connection, order_id, status, **fields)


def set_problem(order_id, message):
    with connect() as connection:
        connection.execute(
            "UPDATE orders SET error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (message, order_id),
        )


def process_order(order, printer_name, wait=True, output_dir=None, simulate=False):
    order_id = order["id"]
    log(
        f"Printing order #{order_id} "
        f"({order['pages']} pages x {order['copies']}, {order['color']}, "
        f"{order['paper']}, {order['sides']}) on {printer_name}"
    )

    pdf_path = order["pdf_path"]
    if not pdf_path or not Path(pdf_path).exists():
        update_order(order_id, "failed", error="The file for this order is missing.")
        log(f"Order #{order_id} failed: file missing")
        return

    if simulate:
        # Safe end-to-end test mode: copy the prepared PDF to the output folder
        # instead of sending anything to a physical printer.
        destination_dir = Path(output_dir or (config.BASE_DIR / "test_prints"))
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"order-{order_id}.pdf"
        shutil.copy2(pdf_path, destination)
        log(f"SIMULATED print for order #{order_id} -> {destination}")
        job_id = None
    else:
        try:
            job_id = printing.print_pdf(
                pdf_path,
                printer_name,
                color=order["color"],
                copies=order["copies"],
                paper=order["paper"],
                duplex=order["sides"] == "double",
                document_name=f"Printify order #{order_id}",
                output_file=Path(output_dir) / f"order-{order_id}.pdf" if output_dir else None,
            )
        except printing.PrintError as error:
            update_order(order_id, "failed", error=str(error))
            log(f"Order #{order_id} failed: {error}")
            return

    if wait and not simulate:
        # Show printer problems (out of paper, offline...) on the order
        finished = printing.wait_for_job(
            printer_name, job_id, on_problem=lambda message: set_problem(order_id, message)
        )
        if not finished:
            update_order(
                order_id, "failed",
                error="The printer did not finish in time (is it switched on?). The job is "
                      "still in the Windows print queue and will print when the printer is "
                      "back, so only retry after clearing that queue.",
            )
            log(f"Order #{order_id} timed out waiting for the printer")
            return

    with connect() as connection:
        set_order_status(
            connection, order_id, "completed",
            error=None,
            printed_at=connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0],
        )
        # Printed: the customer's document is not kept
        forget_document(connection, order_id)
    log(f"Order #{order_id} printed, document deleted")


def delete_old_uploads(keep_days):
    """Delete customer files older than keep_days that no open order needs."""

    with connect() as connection:
        uploads = connection.execute(
            """
            SELECT id FROM uploads
            WHERE created_at < datetime('now', ?)
              AND id NOT IN (
                  SELECT upload_id FROM orders
                  WHERE upload_id IS NOT NULL
                    AND status IN ('awaiting_payment', 'queued', 'printing', 'failed')
              )
            """,
            (f"-{keep_days} days",),
        ).fetchall()

        for upload in uploads:
            shutil.rmtree(config.UPLOAD_FOLDER / upload["id"], ignore_errors=True)
            connection.execute("DELETE FROM uploads WHERE id = ?", (upload["id"],))

    if uploads:
        log(f"Deleted {len(uploads)} old upload(s)")


def recover_interrupted_orders():
    """Orders left 'printing' when the agent stopped are marked failed for review."""

    with connect() as connection:
        count = connection.execute(
            """
            UPDATE orders
            SET status = 'failed',
                error = 'Printing was interrupted. Check the output, then retry or complete.',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'printing'
            """
        ).rowcount
    if count:
        log(f"{count} interrupted order(s) marked as failed")


def main():
    parser = argparse.ArgumentParser(description="Printify print agent")
    parser.add_argument("--printer", default=config.PRINTER_NAME or None,
                        help="printer name (default: PRINTIFY_PRINTER or the Windows default)")
    parser.add_argument("--once", action="store_true", help="print queued orders and exit")
    parser.add_argument("--interval", type=float, default=3, help="seconds between queue checks")
    parser.add_argument("--output-dir",
                        help="print to files in this folder instead of paper "
                             "(for virtual printers such as Microsoft Print to PDF)")
    parser.add_argument("--keep-days", type=float, default=config.KEEP_UPLOADS_DAYS,
                        help="delete uploaded files after this many days (0 = never)")
    parser.add_argument("--no-wait", action="store_true",
                        help="mark orders done once spooled, without waiting for the printer")
    parser.add_argument("--simulate", action="store_true",
                        help="TEST ONLY: simulate printing by copying PDFs to test_prints/; no printer needed")
    args = parser.parse_args()

    printer_name = args.printer or printing.default_printer()
    if not printer_name and not args.simulate:
        sys.exit("No printer found. Set PRINTIFY_PRINTER or pass --printer. For browser testing use --simulate.")
    if args.simulate and not printer_name:
        printer_name = "SIMULATED PRINTER"

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    init_db()
    recover_interrupted_orders()

    if args.simulate:
        log(f"Printer: {printer_name} - SIMULATION MODE (no paper will be used)")
    else:
        info = printing.printer_info(printer_name)
        log(f"Printer: {printer_name} - {info['message']}")
    log("Waiting for orders... (Ctrl+C to stop)" if not args.once else "Processing queue")

    last_cleanup = 0

    try:
        while True:
            if args.keep_days > 0 and time.monotonic() - last_cleanup > 3600:
                delete_old_uploads(args.keep_days)
                last_cleanup = time.monotonic()

            order = claim_next_order()
            if order is not None:
                try:
                    process_order(
                        order, printer_name,
                        wait=not args.no_wait, output_dir=args.output_dir, simulate=args.simulate,
                    )
                except Exception as error:  # keep the agent running
                    update_order(order["id"], "failed", error=f"Unexpected error: {error}")
                    log(f"Order #{order['id']} failed unexpectedly: {error!r}")
                continue
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("Stopped")


if __name__ == "__main__":
    main()
