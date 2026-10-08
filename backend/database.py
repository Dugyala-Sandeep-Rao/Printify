import shutil
import sqlite3
from contextlib import contextmanager

import config


# Order lifecycle:
#   awaiting_payment -> queued -> printing -> completed
#   awaiting_payment -> queued (Razorpay, payment signature checked by the server)
#   awaiting_payment -> verifying (UPI, shop checks the UTR) -> queued
#                                  printing -> failed -> queued (retry)
#   awaiting_payment / verifying / queued / failed -> cancelled
ORDER_STATUSES = (
    "awaiting_payment",
    "verifying",
    "queued",
    "printing",
    "completed",
    "failed",
    "cancelled",
)


def get_connection():
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(config.DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


@contextmanager
def connect():
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# Columns added after the first version of the orders table.
ORDER_EXTRA_COLUMNS = {
    "upload_id": "TEXT",
    "pdf_path": "TEXT",
    "access_token": "TEXT",
    "payment_ref": "TEXT",
    "gateway_order_id": "TEXT",
    "paid_at": "TIMESTAMP",
    "printed_at": "TIMESTAMP",
    "error": "TEXT",
    "updated_at": "TIMESTAMP",
}


def init_db():
    with connect() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_path TEXT NOT NULL,
                pdf_path TEXT NOT NULL,
                pages INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                pages INTEGER NOT NULL,
                color TEXT NOT NULL,
                copies INTEGER NOT NULL,
                paper TEXT NOT NULL,
                sides TEXT NOT NULL,
                total_price REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'awaiting_payment',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Upgrade databases created by the first version of the project
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(orders)")
        }
        for column, column_type in ORDER_EXTRA_COLUMNS.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE orders ADD COLUMN {column} {column_type}"
                )

        # The first version saved unpaid orders as 'pending'
        connection.execute(
            "UPDATE orders SET status = 'awaiting_payment' "
            "WHERE status = 'pending' AND paid_at IS NULL"
        )


def set_order_status(connection, order_id, status, **fields):
    assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    values = [status]

    for column, value in fields.items():
        assignments.append(f"{column} = ?")
        values.append(value)

    values.append(order_id)

    connection.execute(
        f"UPDATE orders SET {', '.join(assignments)} WHERE id = ?",
        values,
    )


# Shown instead of the file name once a printed document has been deleted
DELETED_DOCUMENT_NAME = "Deleted after printing"


def forget_document(connection, order_id):
    """Delete a printed order's file and its name, keeping only the order record.

    The upload is kept if another unfinished order still uses the same file.
    """

    order = connection.execute(
        "SELECT upload_id, pdf_path FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
    if order is None:
        return

    upload_id = order["upload_id"]

    if upload_id:
        still_needed = connection.execute(
            """
            SELECT 1 FROM orders
            WHERE upload_id = ? AND id != ?
              AND status IN ('awaiting_payment', 'verifying', 'queued', 'printing', 'failed')
            """,
            (upload_id, order_id),
        ).fetchone()

        if not still_needed:
            shutil.rmtree(config.UPLOAD_FOLDER / upload_id, ignore_errors=True)
            connection.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))

    connection.execute(
        """
        UPDATE orders
        SET filename = ?, pdf_path = NULL, upload_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (DELETED_DOCUMENT_NAME, order_id),
    )


if __name__ == "__main__":
    init_db()
    print("Database ready:", config.DATABASE_PATH)
