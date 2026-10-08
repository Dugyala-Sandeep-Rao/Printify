const API_BASE =
    location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

const TOKEN_KEY = "printify-admin-token";

const STATUS_TEXT = {
    awaiting_payment: "Awaiting payment",
    verifying: "Check payment",
    queued: "In queue",
    printing: "Printing",
    completed: "Completed",
    failed: "Needs attention",
    cancelled: "Cancelled"
};


// ==========================================
// ELEMENTS
// ==========================================

const loginCard = document.getElementById("loginCard");
const loginForm = document.getElementById("loginForm");
const tokenInput = document.getElementById("tokenInput");
const loginError = document.getElementById("loginError");
const logoutLink = document.getElementById("logoutLink");

const dashboard = document.getElementById("dashboard");
const printerName = document.getElementById("printerName");
const printerMessage = document.getElementById("printerMessage");
const queueCount = document.getElementById("queueCount");
const failedCount = document.getElementById("failedCount");
const revenue = document.getElementById("revenue");

const statusFilter = document.getElementById("statusFilter");
const ordersBody = document.getElementById("ordersBody");
const emptyState = document.getElementById("emptyState");


let adminToken = "";
let refreshTimer = null;


// ==========================================
// API
// ==========================================

async function adminApi(path, options = {}) {

    const response = await fetch(API_BASE + path, {
        ...options,
        headers: { "X-Admin-Token": adminToken, ...(options.headers || {}) }
    });

    if (response.status === 401) {
        logout("Invalid admin token.");
        throw new Error("Invalid admin token");
    }

    if (!response.ok) {
        let message = "Request failed (" + response.status + ")";
        try {
            const data = await response.json();
            if (typeof data.detail === "string") {
                message = data.detail;
            }
        } catch {
            // not JSON
        }
        throw new Error(message);
    }

    return response;
}


// ==========================================
// LOGIN
// ==========================================

loginForm.addEventListener("submit", async (event) => {

    event.preventDefault();

    adminToken = tokenInput.value.trim();

    loginError.hidden = true;
    loginError.textContent = "";

    try {
        await loadOrders();
        try {
            sessionStorage.setItem(TOKEN_KEY, adminToken);
        } catch {
            // storage unavailable
        }
        showDashboard();
    } catch (error) {
        if (!loginError.textContent) {
            loginError.textContent = error instanceof TypeError
                ? "Could not connect to the Printify server."
                : error.message;
        }
        loginError.hidden = false;
    }
});

function showDashboard() {
    loginCard.hidden = true;
    dashboard.hidden = false;
    logoutLink.hidden = false;

    clearInterval(refreshTimer);
    refreshTimer = setInterval(() => loadOrders().catch(console.error), 5000);
}

function logout(message) {
    adminToken = "";
    try {
        sessionStorage.removeItem(TOKEN_KEY);
    } catch {
        // ignore
    }

    clearInterval(refreshTimer);

    dashboard.hidden = true;
    logoutLink.hidden = true;
    loginCard.hidden = false;

    loginError.textContent = message || "";
    loginError.hidden = !message;
}

logoutLink.addEventListener("click", (event) => {
    event.preventDefault();
    logout();
});


// ==========================================
// ORDERS
// ==========================================

function rupees(amount) {
    return "₹" + Number(amount).toLocaleString("en-IN");
}

function formatTime(timestamp) {
    if (!timestamp) {
        return "";
    }
    // SQLite CURRENT_TIMESTAMP is UTC
    const date = new Date(timestamp.replace(" ", "T") + "Z");
    return date.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit"
    });
}

function cell(row, text, className) {
    const td = document.createElement("td");
    if (className) {
        td.className = className;
    }
    td.textContent = text;
    row.appendChild(td);
    return td;
}

function addNote(parent, text, className) {
    const note = document.createElement("span");
    note.className = className;
    note.textContent = text;
    parent.appendChild(note);
}

function actionButton(parent, label, handler, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (className) {
        button.className = className;
    }
    button.addEventListener("click", handler);
    parent.appendChild(button);
}

async function orderAction(order, action, question) {

    if (question && !confirm(question)) {
        return;
    }

    try {
        await adminApi("/api/admin/orders/" + order.id + "/" + action, {
            method: "POST"
        });
        await loadOrders();
    } catch (error) {
        alert(error.message);
    }
}

function renderOrders(orders) {

    ordersBody.replaceChildren();

    emptyState.hidden = orders.length > 0;

    for (const order of orders) {

        const row = document.createElement("tr");

        cell(row, order.id);

        const fileCell = cell(row, order.filename, "file-cell");
        if (!order.has_file && order.status === "completed") {
            fileCell.classList.add("deleted");
        }
        fileCell.title = order.filename;
        if (order.payment_ref) {
            addNote(fileCell, order.payment_ref, "muted");
        }

        cell(
            row,
            order.pages + "p × " + order.copies + " • " +
            (order.color === "color" ? "Colour" : "B&W") + " • " +
            order.paper.toUpperCase() + " • " +
            (order.sides === "double" ? "Double" : "Single")
        );

        cell(row, rupees(order.total_price));

        const statusCell = cell(row, "");
        const pill = document.createElement("span");
        pill.className = "status-pill";
        pill.dataset.status = order.status;
        pill.textContent = STATUS_TEXT[order.status] || order.status;
        statusCell.appendChild(pill);
        if (order.error) {
            addNote(statusCell, order.error, "error-text");
        }

        const placed = cell(row, formatTime(order.created_at));
        if (order.printed_at) {
            addNote(placed, "Printed " + formatTime(order.printed_at), "muted");
        }

        const actionsCell = cell(row, "");
        const actions = document.createElement("div");
        actions.className = "row-actions";
        actionsCell.appendChild(actions);

        if (order.status === "verifying") {
            row.classList.add("needs-check");
            actionButton(actions, "\u2713 Confirm payment", () =>
                orderAction(order, "confirm-payment",
                    "Did you receive " + rupees(order.total_price) + " with " +
                    order.payment_ref + " in your UPI app?"), "confirm");
            actionButton(actions, "Reject", () =>
                orderAction(order, "reject-payment",
                    "No payment found for " + order.payment_ref + "? The customer will be asked to pay again."),
                "danger");
        }

        if ((order.status === "failed" || order.status === "completed") && order.has_file) {
            actionButton(
                actions,
                order.status === "failed" ? "Retry" : "Reprint",
                () => orderAction(order, "retry",
                    order.status === "completed"
                        ? "Print order #" + order.id + " again?"
                        : null)
            );
        }

        if (["queued", "printing", "failed"].includes(order.status)) {
            actionButton(actions, "Mark done", () =>
                orderAction(order, "complete", "Mark order #" + order.id + " as completed?"));
        }

        if (["awaiting_payment", "verifying", "queued", "failed"].includes(order.status)) {
            actionButton(actions, "Cancel", () =>
                orderAction(order, "cancel", "Cancel order #" + order.id + "?"), "danger");
        }

        ordersBody.appendChild(row);
    }
}

async function loadOrders() {

    const query = statusFilter.value
        ? "?status=" + encodeURIComponent(statusFilter.value)
        : "";

    const response = await adminApi("/api/admin/orders" + query);
    const data = await response.json();

    printerName.textContent = data.printer.name || "None";
    printerName.title = data.printer.name || "";
    printerMessage.textContent = data.printer.message;
    printerMessage.classList.toggle("problem", !data.printer.ready);

    queueCount.textContent = data.summary.in_queue;
    failedCount.textContent = data.summary.failed + data.summary.verifying;

    // Show waiting payments in the browser tab
    document.title = (data.summary.verifying ? "(" + data.summary.verifying + ") " : "") +
        "Printify | Shop Admin";
    revenue.textContent = rupees(data.summary.revenue);

    renderOrders(data.orders);
}

statusFilter.addEventListener("change", () => loadOrders().catch(console.error));


// ==========================================
// START
// ==========================================

try {
    adminToken = sessionStorage.getItem(TOKEN_KEY) || "";
} catch {
    adminToken = "";
}

if (adminToken) {
    loadOrders().then(showDashboard).catch(() => logout());
}
