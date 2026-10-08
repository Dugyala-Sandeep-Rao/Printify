// ==========================================
// API
// ==========================================

// Served by FastAPI: same origin. Opened as a file: talk to the local backend.
const API_BASE =
    location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

function errorMessage(data, status) {
    const detail = data && data.detail;
    if (typeof detail === "string") {
        return detail;
    }
    if (Array.isArray(detail)) {
        return detail.map((d) => d.msg).join(", ");
    }
    return "Something went wrong (" + status + ")";
}

async function api(path, options = {}) {

    const response = await fetch(API_BASE + path, options);

    let data = null;
    try {
        data = await response.json();
    } catch {
        // Not JSON (e.g. server crashed)
    }

    if (!response.ok) {
        throw new Error(errorMessage(data, response.status));
    }

    return data;
}

function postJson(path, body) {
    return api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
}

// Upload with progress events (fetch can't report upload progress)
function uploadRequest(formData, onProgress) {

    return new Promise((resolve, reject) => {

        const xhr = new XMLHttpRequest();

        xhr.open("POST", API_BASE + "/api/upload");

        xhr.upload.addEventListener("progress", (event) => {
            if (event.lengthComputable) {
                onProgress(event.loaded / event.total);
            }
        });

        xhr.addEventListener("load", () => {
            let data = null;
            try {
                data = JSON.parse(xhr.responseText);
            } catch {
                // not JSON
            }
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(data);
            } else {
                reject(new Error(errorMessage(data, xhr.status)));
            }
        });

        xhr.addEventListener("error", () =>
            reject(new TypeError("Could not connect to the Printify server.")));

        xhr.send(formData);
    });
}


// ==========================================
// ELEMENTS
// ==========================================

const $ = (id) => document.getElementById(id);

const uploadArea = $("uploadArea");
const fileInput = $("fileInput");
const fileName = $("fileName");
const fileIcon = $("fileIcon");
const removeFile = $("removeFile");
const pageInfo = $("pageInfo");
const pageCount = $("pageCount");
const fileStatus = $("fileStatus");
const uploadProgress = $("uploadProgress");
const uploadProgressBar = $("uploadProgressBar");

const printerStatus = $("printerStatus");
const printerStatusText = $("printerStatusText");

const copiesInput = $("copies");

const price = $("price");
const priceDetails = $("priceDetails");

const payBtn = $("payBtn");
const formError = $("formError");
const printCard = $("printCard");
const stepsMini = $("stepsMini").children;

const heroContent = $("heroContent");

// Preview
const previewPanel = $("previewPanel");
const previewTitle = $("previewTitle");
const previewMeta = $("previewMeta");
const sheetStack = $("sheetStack");
const sheet = $("sheet");
const sheetInner = $("sheetInner");
const frontImage = $("frontImage");
const backImage = $("backImage");
const frontLabel = $("frontLabel");
const backLabel = $("backLabel");
const blankNote = $("blankNote");
const copiesSticker = $("copiesSticker");
const prevSheet = $("prevSheet");
const nextSheet = $("nextSheet");
const sheetCounter = $("sheetCounter");
const flipBtn = $("flipBtn");
const thumbs = $("thumbs");

// Payment
const paymentModal = $("paymentModal");
const paymentSummary = $("paymentSummary");
const paymentAmount = $("paymentAmount");
const confirmPayAmount = $("confirmPayAmount");
const confirmPayBtn = $("confirmPayBtn");
const closePayment = $("closePayment");
const upiPay = $("upiPay");
const demoPay = $("demoPay");
const upiOpenBtn = $("upiOpenBtn");
const upiOpenAmount = $("upiOpenAmount");
const upiQr = $("upiQr");
const upiPayee = $("upiPayee");
const upiId = $("upiId");
const utrInput = $("utrInput");
const utrError = $("utrError");
const upiDoneBtn = $("upiDoneBtn");
const rzpPay = $("rzpPay");
const rzpPayBtn = $("rzpPayBtn");
const rzpPayAmount = $("rzpPayAmount");
const rzpTestNote = $("rzpTestNote");
const rzpError = $("rzpError");

// Lightbox
const lightbox = $("lightbox");
const lightboxImage = $("lightboxImage");
const lightboxLabel = $("lightboxLabel");
const closeLightbox = $("closeLightbox");

// Order tracking
const orderPanel = $("orderPanel");
const orderNumber = $("orderNumber");
const orderSummary = $("orderSummary");
const orderBadge = $("orderBadge");
const orderSteps = $("orderSteps");
const orderMessage = $("orderMessage");
const printerScene = $("printerScene");
const cancelOrderBtn = $("cancelOrderBtn");
const payAgainBtn = $("payAgainBtn");
const newOrderBtn = $("newOrderBtn");


// ==========================================
// STATE
// ==========================================

let selectedFile = null;
let uploadId = null;
let totalPages = 0;
let currentTotal = 0;

let sheetIndex = 0;
let flipped = false;

let currentOrder = null;
let currentToken = null;
let trackTimer = null;
let lastStatus = null;

let maxCopies = 100;

// "razorpay" with gateway keys, "upi" with a shop UPI ID, otherwise "demo"
let paymentMode = "demo";
let paymentTestMode = false;

const ORDER_STORAGE_KEY = "printify-order";

// Width / height of each paper size (portrait)
const PAPER_RATIO = { a4: 210 / 297, a3: 297 / 420, letter: 216 / 279 };

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;


// ==========================================
// HELPERS
// ==========================================

function rupees(amount) {
    return "₹" + Math.round(Number(amount)).toLocaleString("en-IN");
}

function getOption(name) {
    return document.querySelector('input[name="' + name + '"]:checked').value;
}

function getCopies() {
    return Math.min(maxCopies, Math.max(1, parseInt(copiesInput.value) || 1));
}

function options() {
    return {
        color: getOption("color"),
        paper: getOption("paper"),
        sides: getOption("sides"),
        copies: getCopies()
    };
}

function showError(message) {
    formError.textContent = message;
    formError.hidden = !message;
}

function toast(message, type) {
    const element = document.createElement("div");
    element.className = "toast" + (type ? " " + type : "");
    element.textContent = message;
    $("toasts").appendChild(element);

    setTimeout(() => {
        element.classList.add("leaving");
        element.addEventListener("animationend", () => element.remove());
    }, 3200);
}

function describeOptions(o) {
    return (
        o.pages + (o.pages === 1 ? " page" : " pages") +
        " × " + o.copies + (o.copies === 1 ? " copy" : " copies") +
        " • " + (o.color === "color" ? "Colour" : "B&W") +
        " • " + o.paper.toUpperCase() +
        " • " + (o.sides === "double" ? "Double-sided" : "Single-sided")
    );
}

function setStep(active) {
    Array.from(stepsMini).forEach((step, index) => {
        step.classList.toggle("done", index < active);
        step.classList.toggle("active", index === active);
    });
}

// Count a number up/down smoothly
function animateNumber(element, from, to, format) {

    if (reduceMotion || from === to) {
        element.textContent = format(to);
        return;
    }

    const start = performance.now();
    const duration = 500;

    function frame(now) {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        element.textContent = format(from + (to - from) * eased);
        if (t < 1) {
            requestAnimationFrame(frame);
        }
    }

    requestAnimationFrame(frame);

    element.classList.remove("bump");
    void element.offsetWidth; // restart animation
    element.classList.add("bump");
}


// ==========================================
// HERO WORD ROTATOR
// ==========================================

const WORDS = ["notes", "resume", "assignment", "slides", "tickets", "memes", "project"];
let wordIndex = 0;
const rotatingWord = $("rotatingWord");

if (!reduceMotion) {
    setInterval(() => {

        if (heroContent.hidden) {
            return;
        }

        rotatingWord.classList.add("swap-out");

        setTimeout(() => {
            wordIndex = (wordIndex + 1) % WORDS.length;
            rotatingWord.textContent = WORDS[wordIndex];
            rotatingWord.classList.remove("swap-out");
            rotatingWord.classList.add("swap-in");
        }, 330);

        setTimeout(() => rotatingWord.classList.remove("swap-in"), 900);

    }, 2400);
}


// ==========================================
// SCROLL REVEAL
// ==========================================

if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("in");
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.15 });

    document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));
} else {
    document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
}


// ==========================================
// CONFETTI
// ==========================================

function confetti() {

    if (reduceMotion) {
        return;
    }

    const canvas = $("confetti");
    const ctx = canvas.getContext("2d");
    const ratio = window.devicePixelRatio || 1;

    canvas.width = innerWidth * ratio;
    canvas.height = innerHeight * ratio;
    ctx.scale(ratio, ratio);

    const colors = ["#ff7a3d", "#ffd23f", "#ff5e62", "#ffb38a", "#2b1810"];

    const pieces = Array.from({ length: 70 }, () => ({
        x: innerWidth / 2 + (Math.random() - 0.5) * 200,
        y: innerHeight * 0.45,
        vx: (Math.random() - 0.5) * 10,
        vy: -Math.random() * 11 - 5,
        size: 4 + Math.random() * 5,
        rotation: Math.random() * Math.PI,
        spin: (Math.random() - 0.5) * 0.3,
        color: colors[Math.floor(Math.random() * colors.length)]
    }));

    const start = performance.now();

    function frame(now) {

        ctx.clearRect(0, 0, innerWidth, innerHeight);

        const elapsed = now - start;

        pieces.forEach((p) => {
            p.vy += 0.3;
            p.vx *= 0.99;
            p.x += p.vx;
            p.y += p.vy;
            p.rotation += p.spin;

            ctx.save();
            ctx.globalAlpha = Math.max(0, 1 - elapsed / 3000);
            ctx.translate(p.x, p.y);
            ctx.rotate(p.rotation);
            ctx.fillStyle = p.color;
            ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
            ctx.restore();
        });

        if (elapsed < 3000) {
            requestAnimationFrame(frame);
        } else {
            ctx.clearRect(0, 0, innerWidth, innerHeight);
        }
    }

    requestAnimationFrame(frame);
}


// ==========================================
// 0. SHOP CONFIGURATION & PRINTER STATUS
// ==========================================

async function loadConfig() {

    try {

        const config = await api("/api/config");

        maxCopies = config.max_copies;
        paymentMode = config.payment.mode;
        paymentTestMode = config.payment.test_mode;

        if (paymentMode === "razorpay") {
            loadRazorpay().catch(() => {});
        }
        copiesInput.max = maxCopies;

        const printer = config.printer;

        // Only offer what the shop printer can do
        document.querySelectorAll('input[name="paper"]').forEach((input) => {
            input.disabled = !printer.papers.includes(input.value);
            input.parentElement.title = input.disabled ? "Not available on this printer" : "";
        });

        if (document.querySelector('input[name="paper"]:checked').disabled) {
            document.querySelector('input[name="paper"][value="' + printer.papers[0] + '"]').checked = true;
        }

        document.querySelector('input[name="sides"][value="double"]').disabled = !printer.duplex;
        document.querySelector('input[name="color"][value="color"]').disabled = !printer.color;

        setPrinterStatus(printer);

    } catch (error) {

        console.error("Config error:", error);

        setPrinterStatus({ ready: false, message: "Server offline" });
    }
}

function setPrinterStatus(printer) {
    printerStatus.classList.toggle("offline", !printer.ready);
    printerStatusText.textContent = printer.ready ? "Printer online" : printer.message;
}


// ==========================================
// 1. FILE SELECTED
// ==========================================

fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
        selectFile(fileInput.files[0]);
    }
});

["dragenter", "dragover"].forEach((type) => {
    uploadArea.addEventListener(type, (event) => {
        event.preventDefault();
        uploadArea.classList.add("dragover");
    });
});

["dragleave", "drop"].forEach((type) => {
    uploadArea.addEventListener(type, (event) => {
        event.preventDefault();
        uploadArea.classList.remove("dragover");
    });
});

uploadArea.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    if (file) {
        selectFile(file);
    }
});

function fileBadge(name) {
    const extension = (name.split(".").pop() || "").toUpperCase();
    return extension.length <= 4 ? extension : "FILE";
}

async function selectFile(file) {

    selectedFile = file;
    uploadId = null;
    totalPages = 0;

    showError("");

    fileName.textContent = file.name;
    fileIcon.textContent = fileBadge(file.name);
    uploadArea.classList.add("has-file");
    pageInfo.style.display = "none";

    hidePreview();
    updatePrice();

    await uploadFile(file);
}


// ==========================================
// 2. REMOVE SELECTED FILE
// ==========================================

function resetFile() {

    selectedFile = null;
    uploadId = null;
    totalPages = 0;

    fileInput.value = "";

    uploadArea.classList.remove("has-file");

    pageCount.textContent = "0";
    pageInfo.style.display = "none";

    fileStatus.textContent = "Ready to upload";
    uploadProgress.className = "progress";
    uploadProgressBar.style.width = "0";

    showError("");
    hidePreview();
    setStep(0);
    updatePrice();
}

removeFile.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    resetFile();
});


// ==========================================
// 3. UPLOAD
// ==========================================

async function uploadFile(file) {

    const formData = new FormData();
    formData.append("file", file);
    formData.append("paper_size", getOption("paper"));

    const needsConversion = /\.(docx?|pptx?|xlsx?|odt|odp|ods|txt)$/i.test(file.name);

    fileStatus.textContent = "Uploading... 0%";
    uploadProgress.className = "progress";
    uploadProgressBar.style.width = "0";

    payBtn.disabled = true;

    try {

        const result = await uploadRequest(formData, (fraction) => {

            if (selectedFile !== file) {
                return;
            }

            uploadProgressBar.style.width = Math.round(fraction * 100) + "%";

            if (fraction >= 1) {
                // Uploaded; the server is now converting / counting pages
                uploadProgress.className = "progress indeterminate";
                fileStatus.textContent = needsConversion
                    ? "Converting to PDF..."
                    : "Reading pages...";
            } else {
                fileStatus.textContent = "Uploading... " + Math.round(fraction * 100) + "%";
            }
        });

        // A different file was chosen while this one uploaded
        if (selectedFile !== file) {
            return;
        }

        uploadId = result.upload_id;
        totalPages = result.pages;

        pageCount.textContent = totalPages;
        pageInfo.style.display = "inline";

        uploadProgress.className = "progress complete";
        fileStatus.textContent = "Ready";

        setStep(1);
        showPreview(result.filename);
        updatePrice();

        if (window.fxBurst) {
            window.fxBurst(fileIcon);
        }

        toast(totalPages + (totalPages === 1 ? " page" : " pages") + " ready to print");

    } catch (error) {

        if (selectedFile !== file) {
            return;
        }

        console.error("Upload error:", error);

        uploadProgress.className = "progress";
        uploadProgressBar.style.width = "0";
        fileStatus.textContent = "Upload failed";

        showError(error.message);

    } finally {

        payBtn.disabled = false;
    }
}


// ==========================================
// 4. PRINT PREVIEW
// ==========================================

function pageUrl(page, size) {
    return API_BASE + "/api/uploads/" + uploadId + "/pages/" + page + "?size=" + size;
}

function sheetCount() {
    return getOption("sides") === "double"
        ? Math.ceil(totalPages / 2)
        : totalPages;
}

// Pages printed on a sheet: [front, back or null]
function sheetPages(index) {
    if (getOption("sides") === "double") {
        const front = index * 2 + 1;
        return [front, front + 1 <= totalPages ? front + 1 : null];
    }
    return [index + 1, null];
}

function showPreview(name) {

    previewTitle.textContent = name;

    heroContent.hidden = true;
    previewPanel.hidden = false;

    sheetIndex = 0;

    buildThumbs();
    showSheet(0, 0);
    updatePreviewStyle();
}

function hidePreview() {
    previewPanel.hidden = true;
    heroContent.hidden = false;
    thumbs.replaceChildren();
}

function loadInto(image, face, src) {
    face.classList.add("is-loading");
    image.classList.add("loading");
    image.onload = () => {
        face.classList.remove("is-loading");
        image.classList.remove("loading");
        if (image === frontImage) {
            setOrientation(image.naturalWidth > image.naturalHeight);
        }
    };
    image.src = src;
}

function setOrientation(landscape) {
    const ratio = PAPER_RATIO[getOption("paper")];
    sheetStack.classList.toggle("landscape", landscape);
    sheetStack.style.setProperty("--sheet-ratio", landscape ? 1 / ratio : ratio);
}

function showSheet(index, direction) {

    const count = sheetCount();
    sheetIndex = Math.max(0, Math.min(index, count - 1));

    const [front, back] = sheetPages(sheetIndex);
    const double = getOption("sides") === "double";

    loadInto(frontImage, frontImage.parentElement, pageUrl(front, "large"));
    frontImage.alt = "Page " + front;
    frontLabel.textContent = "Page " + front;

    if (back) {
        loadInto(backImage, backImage.parentElement, pageUrl(back, "large"));
        backImage.hidden = false;
        blankNote.hidden = true;
        backLabel.textContent = "Page " + back;
    } else {
        backImage.removeAttribute("src");
        backImage.hidden = true;
        blankNote.hidden = false;
        backLabel.textContent = "Back";
    }

    // Flip back to the front for a new sheet
    flipped = false;
    sheetInner.classList.remove("flipped");

    if (direction) {
        sheet.classList.remove("enter", "enter-back");
        void sheet.offsetWidth;
        sheet.classList.add(direction > 0 ? "enter" : "enter-back");
    }

    sheetCounter.textContent = "Sheet " + (sheetIndex + 1) + " of " + count +
        (double ? " · front" : "");

    flipBtn.hidden = !double;
    prevSheet.disabled = sheetIndex === 0;
    nextSheet.disabled = sheetIndex >= count - 1;

    // Highlight the thumbnail
    thumbs.querySelectorAll(".thumb-group").forEach((group, i) => {
        const active = i === sheetIndex;
        group.classList.toggle("active", active);
        if (active) {
            group.scrollIntoView({ block: "nearest", inline: "center", behavior: reduceMotion ? "auto" : "smooth" });
        }
    });

    // Warm the cache for the next sheet
    if (sheetIndex + 1 < count) {
        sheetPages(sheetIndex + 1).filter(Boolean).forEach((page) => {
            new Image().src = pageUrl(page, "large");
        });
    }
}

function buildThumbs() {

    thumbs.replaceChildren();

    for (let i = 0; i < sheetCount(); i++) {

        const group = document.createElement("button");
        group.type = "button";
        group.className = "thumb-group";
        group.style.setProperty("--i", i);
        group.setAttribute("aria-label", "Sheet " + (i + 1));

        sheetPages(i).forEach((page, side) => {

            if (page === null && side === 1) {
                if (getOption("sides") === "double") {
                    const blank = document.createElement("span");
                    blank.className = "thumb blank";
                    group.appendChild(blank);
                }
                return;
            }

            if (page === null) {
                return;
            }

            const thumb = document.createElement("span");
            thumb.className = "thumb";

            const image = document.createElement("img");
            image.loading = "lazy";
            image.alt = "";
            image.src = pageUrl(page, "small");

            const label = document.createElement("span");
            label.textContent = page;

            thumb.append(image, label);
            group.appendChild(thumb);
        });

        group.addEventListener("click", () => showSheet(i, i > sheetIndex ? 1 : -1));

        thumbs.appendChild(group);
    }
}

function updatePreviewStyle() {

    if (previewPanel.hidden) {
        return;
    }

    const o = options();

    previewPanel.classList.toggle("bw", o.color === "bw");
    lightbox.classList.toggle("bw", o.color === "bw");

    setOrientation(sheetStack.classList.contains("landscape"));

    // Stack of copies behind the sheet
    sheetStack.classList.remove("copies-2", "copies-3");
    if (o.copies >= 3) {
        sheetStack.classList.add("copies-3");
    } else if (o.copies === 2) {
        sheetStack.classList.add("copies-2");
    }

    copiesSticker.hidden = o.copies < 2;
    copiesSticker.textContent = "×" + o.copies;

    const sheets = sheetCount();

    previewMeta.replaceChildren(
        ...[
            [totalPages + (totalPages === 1 ? " page" : " pages"), false],
            [sheets * o.copies + (sheets * o.copies === 1 ? " sheet" : " sheets"), true],
            [o.color === "color" ? "Colour" : "Black & white", false],
            [o.paper.toUpperCase(), false],
            [o.sides === "double" ? "Double-sided" : "Single-sided", false]
        ].map(([text, accent]) => {
            const chip = document.createElement("span");
            chip.className = "meta-chip" + (accent ? " accent" : "");
            chip.textContent = text;
            return chip;
        })
    );
}

flipBtn.addEventListener("click", () => {

    flipped = !flipped;
    sheetInner.classList.toggle("flipped", flipped);

    sheetCounter.textContent = "Sheet " + (sheetIndex + 1) + " of " + sheetCount() +
        (flipped ? " · back" : " · front");
});

prevSheet.addEventListener("click", () => showSheet(sheetIndex - 1, -1));
nextSheet.addEventListener("click", () => showSheet(sheetIndex + 1, 1));

document.addEventListener("keydown", (event) => {

    if (previewPanel.hidden || !paymentModal.hidden ||
        ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
        return;
    }

    if (event.key === "ArrowRight") {
        showSheet(sheetIndex + 1, 1);
    } else if (event.key === "ArrowLeft") {
        showSheet(sheetIndex - 1, -1);
    }
});

// Swipe between sheets on phones
let touchStartX = null;
let swiped = false;

sheet.addEventListener("touchstart", (event) => {
    touchStartX = event.touches[0].clientX;
}, { passive: true });

sheet.addEventListener("touchend", (event) => {
    if (touchStartX === null) {
        return;
    }
    const dx = event.changedTouches[0].clientX - touchStartX;
    touchStartX = null;
    if (Math.abs(dx) > 50) {
        swiped = true;
        showSheet(sheetIndex + (dx < 0 ? 1 : -1), dx < 0 ? 1 : -1);
    }
});


// Zoom

sheet.addEventListener("click", () => {

    if (swiped) {
        swiped = false;
        return;
    }

    const [front, back] = sheetPages(sheetIndex);
    const page = flipped ? back : front;

    if (!page) {
        return;
    }

    lightboxImage.src = pageUrl(page, "large");
    lightboxImage.alt = "Page " + page;
    lightboxLabel.textContent = "Page " + page + " of " + totalPages;
    lightbox.hidden = false;
});

function closeLightboxView() {
    lightbox.hidden = true;
}

closeLightbox.addEventListener("click", closeLightboxView);

lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) {
        closeLightboxView();
    }
});


// ==========================================
// 5. PRICE (calculated by the server)
// ==========================================

let quoteRequest = 0;
let shownTotal = 0;

async function updatePrice() {

    if (totalPages <= 0) {
        currentTotal = 0;
        animateNumber(price, shownTotal, 0, rupees);
        shownTotal = 0;
        priceDetails.textContent = "Upload a document to see the price";
        return;
    }

    const o = { pages: totalPages, ...options() };
    const request = ++quoteRequest;

    try {

        const quote = await postJson("/api/quote", o);

        // Ignore answers to older requests
        if (request !== quoteRequest) {
            return;
        }

        currentTotal = quote.total;

        animateNumber(price, shownTotal, quote.total, rupees);
        shownTotal = quote.total;

        priceDetails.textContent =
            describeOptions(o) +
            (o.sides === "double"
                ? " (" + quote.sheets + (quote.sheets === 1 ? " sheet)" : " sheets)")
                : "");

    } catch (error) {
        console.error("Quote error:", error);
        priceDetails.textContent = "Could not calculate the price";
    }
}


// ==========================================
// 6. OPTION EVENTS
// ==========================================

document.querySelectorAll(".segmented input").forEach((input) => {
    input.addEventListener("change", () => {

        if (input.name === "sides" && !previewPanel.hidden) {
            // Sheets change when switching single / double
            const firstPage = sheetPages(sheetIndex)[0];
            buildThumbs();
            showSheet(input.value === "double"
                ? Math.floor((firstPage - 1) / 2)
                : firstPage - 1, 0);
        }

        updatePreviewStyle();
        updatePrice();
    });
});

function setCopies(value) {
    copiesInput.value = Math.min(maxCopies, Math.max(1, value));
    updatePreviewStyle();
    updatePrice();
}

$("copiesMinus").addEventListener("click", () => setCopies(getCopies() - 1));
$("copiesPlus").addEventListener("click", () => setCopies(getCopies() + 1));

copiesInput.addEventListener("input", () => {
    updatePreviewStyle();
    updatePrice();
});

copiesInput.addEventListener("change", () => setCopies(getCopies()));


// ==========================================
// 7. PAY & PRINT
// ==========================================

payBtn.addEventListener("click", async () => {

    showError("");

    if (!selectedFile) {
        showError("Please upload a document first.");
        uploadArea.classList.remove("dragover");
        return;
    }

    if (!uploadId || totalPages <= 0) {
        showError("Hang on, your file is still uploading.");
        return;
    }

    try {

        payBtn.disabled = true;
        payBtn.firstElementChild.textContent = "Creating order...";

        const result = await postJson("/api/orders", {
            upload_id: uploadId,
            ...options()
        });

        currentOrder = result.order;
        currentToken = result.token;

        setStep(2);
        openPayment(currentOrder);

    } catch (error) {

        console.error("Order error:", error);
        showError(error.message);

    } finally {

        payBtn.disabled = false;
        payBtn.firstElementChild.textContent = "Pay & Print";
    }
});

async function openPayment(order) {

    paymentSummary.textContent = order.filename + " \u2022 " + describeOptions(order);
    paymentAmount.textContent = rupees(order.total_price);
    confirmPayAmount.textContent = rupees(order.total_price);

    upiPay.hidden = paymentMode !== "upi";
    rzpPay.hidden = paymentMode !== "razorpay";
    demoPay.hidden = paymentMode !== "demo";

    if (paymentMode === "razorpay") {
        rzpPayAmount.textContent = rupees(order.total_price);
        rzpTestNote.hidden = !paymentTestMode;
        rzpError.hidden = true;
    }

    if (paymentMode === "upi") {

        const query = "?token=" + encodeURIComponent(currentToken);

        try {
            const upi = await api("/api/orders/" + order.id + "/upi" + query);

            upiOpenBtn.href = upi.link;
            upiOpenAmount.textContent = rupees(upi.amount);
            upiPayee.textContent = upi.name;
            upiId.textContent = upi.upi_id;
            upiQr.src = API_BASE + "/api/orders/" + order.id + "/upi-qr.png" + query;

        } catch (error) {
            toast(error.message, "error");
            return;
        }

        utrInput.value = "";
        utrError.hidden = true;
    }

    paymentModal.hidden = false;

    ({ upi: upiOpenBtn, razorpay: rzpPayBtn }[paymentMode] || confirmPayBtn).focus();
}

function closePaymentModal() {
    paymentModal.hidden = true;
    if (orderPanel.hidden) {
        setStep(1);
    }
}

closePayment.addEventListener("click", closePaymentModal);

paymentModal.addEventListener("click", (event) => {
    if (event.target === paymentModal) {
        closePaymentModal();
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }
    if (!lightbox.hidden) {
        closeLightboxView();
    } else if (!paymentModal.hidden) {
        closePaymentModal();
    }
});

confirmPayBtn.addEventListener("click", async () => {

    const method = document.querySelector('input[name="payMethod"]:checked').value;

    try {

        confirmPayBtn.disabled = true;
        confirmPayBtn.firstElementChild.textContent = "Processing...";

        const result = await postJson(
            "/api/orders/" + currentOrder.id + "/pay",
            { token: currentToken, method: method }
        );

        paymentModal.hidden = true;

        saveTrackedOrder(result.order.id, currentToken);

        showOrder(result.order);
        startTracking();

        confetti();
        toast("Payment received. Your order is in the queue.");

    } catch (error) {

        console.error("Payment error:", error);
        toast("Payment failed: " + error.message, "error");

    } finally {

        confirmPayBtn.disabled = false;
        confirmPayBtn.firstElementChild.textContent = "Pay now";
    }
});


// Razorpay: checkout popup with UPI, cards, netbanking and wallets

let razorpayScript = null;

function loadRazorpay() {
    if (!razorpayScript) {
        razorpayScript = new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = "https://checkout.razorpay.com/v1/checkout.js";
            script.onload = resolve;
            script.onerror = () => {
                razorpayScript = null;
                reject(new Error("Could not load Razorpay. Check your internet connection."));
            };
            document.head.appendChild(script);
        });
    }
    return razorpayScript;
}

function razorpayPaid(order) {
    paymentModal.hidden = true;

    saveTrackedOrder(order.id, currentToken);

    showOrder(order);
    startTracking();

    confetti();
    toast("Payment received. Your order is in the queue.");
}

function showRazorpayError(message) {
    rzpError.textContent = message;
    rzpError.hidden = false;
}

function resetRazorpayButton() {
    rzpPayBtn.disabled = false;
    rzpPayBtn.firstElementChild.textContent = "Pay securely";
}

rzpPayBtn.addEventListener("click", async () => {

    rzpError.hidden = true;
    rzpPayBtn.disabled = true;
    rzpPayBtn.firstElementChild.textContent = "Opening...";

    try {

        await loadRazorpay();

        const checkout = await postJson(
            "/api/orders/" + currentOrder.id + "/razorpay",
            { token: currentToken }
        );

        // Already paid earlier (e.g. the page closed before we heard back)
        if (checkout.status === "paid") {
            resetRazorpayButton();
            razorpayPaid(checkout.order);
            return;
        }

        const popup = new window.Razorpay({
            key: checkout.key_id,
            order_id: checkout.razorpay_order_id,
            amount: checkout.amount,
            currency: checkout.currency,
            name: checkout.name,
            description: checkout.description,
            theme: { color: getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#dd4f10" },

            handler: async (response) => {
                rzpPayBtn.firstElementChild.textContent = "Confirming...";
                try {
                    const result = await postJson(
                        "/api/orders/" + currentOrder.id + "/razorpay/verify",
                        { token: currentToken, ...response }
                    );
                    razorpayPaid(result.order);
                } catch (error) {
                    showRazorpayError(error.message + " If money was taken, show order #" +
                        currentOrder.id + " to the shop staff.");
                } finally {
                    resetRazorpayButton();
                }
            },

            modal: {
                ondismiss: resetRazorpayButton
            }
        });

        popup.on("payment.failed", (response) => {
            showRazorpayError("Payment failed: " + response.error.description + " Please try again.");
        });

        popup.open();

    } catch (error) {

        console.error("Razorpay error:", error);
        showRazorpayError(error.message);
        resetRazorpayButton();
    }
});


// UPI: customer paid in their app and types the UTR

utrInput.addEventListener("input", () => {
    // Keep digits only, grouped for readability
    const digits = utrInput.value.replace(/\D/g, "").slice(0, 12);
    utrInput.value = digits;
    utrError.hidden = true;
});

upiDoneBtn.addEventListener("click", async () => {

    const utr = utrInput.value.replace(/\D/g, "");

    if (utr.length !== 12) {
        utrError.textContent = "The UPI reference number has 12 digits. You'll find it on the payment receipt in your UPI app.";
        utrError.hidden = false;
        utrInput.focus();
        return;
    }

    try {

        upiDoneBtn.disabled = true;
        upiDoneBtn.firstElementChild.textContent = "Sending...";

        const result = await postJson(
            "/api/orders/" + currentOrder.id + "/upi-paid",
            { token: currentToken, utr: utr }
        );

        paymentModal.hidden = true;

        saveTrackedOrder(result.order.id, currentToken);

        showOrder(result.order);
        startTracking();

        toast("Thank you. The shop is confirming your payment.");

    } catch (error) {

        utrError.textContent = error.message;
        utrError.hidden = false;

    } finally {

        upiDoneBtn.disabled = false;
        upiDoneBtn.firstElementChild.textContent = "I've paid";
    }
});


// ==========================================
// 8. ORDER TRACKING
// ==========================================

const STATUS_TEXT = {
    awaiting_payment: "Awaiting payment",
    verifying: "Checking payment",
    queued: "In queue",
    printing: "Printing",
    completed: "Ready",
    failed: "Needs attention",
    cancelled: "Cancelled"
};

const STEP_ORDER = ["queued", "printing", "completed"];

function saveTrackedOrder(id, token) {
    try {
        localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify({ id: id, token: token }));
    } catch {
        // Storage unavailable: tracking just won't survive reloads
    }
}

function clearTrackedOrder() {
    try {
        localStorage.removeItem(ORDER_STORAGE_KEY);
    } catch {
        // ignore
    }
}

function showOrder(order) {

    currentOrder = order;

    printCard.hidden = true;
    orderPanel.hidden = false;

    orderNumber.textContent = "#" + order.id;
    orderSummary.textContent = order.filename + " • " + rupees(order.total_price);

    orderBadge.textContent = STATUS_TEXT[order.status] || order.status;
    orderBadge.dataset.status = order.status;

    printerScene.dataset.status = order.status;

    const reached = STEP_ORDER.indexOf(order.status);
    orderSteps.style.setProperty("--progress", Math.max(0, reached) / 2);
    orderSteps.querySelectorAll("li").forEach((step, index) => {
        step.classList.toggle("done", reached >= 0 && index <= reached);
        step.classList.toggle("current", index === reached);
    });
    orderSteps.hidden = order.status === "cancelled";

    let message;

    if (order.status === "verifying") {
        message = "We got your UPI reference number. The shop is checking the payment, " +
            "this usually takes a minute. Printing starts right after ⏳";
    } else if (order.status === "awaiting_payment" && order.error) {
        message = order.error + " Please check your UPI app and pay again, or talk to the shop staff.";
    } else if (order.status === "queued") {
        message = order.queue_position > 1
            ? "Payment received. " + (order.queue_position - 1) + " order(s) ahead of yours."
            : "Payment received. Your order is next in line.";
    } else if (order.status === "printing") {
        message = order.error
            ? "Printing paused: " + order.error + ". The shop has been told."
            : "Your pages are printing now.";
    } else if (order.status === "completed") {
        message = "Done! Show order number #" + order.id + " at the counter to collect your prints.";
    } else if (order.status === "failed") {
        message = "Something went wrong while printing" +
            (order.error ? " (" + order.error + ")" : "") +
            ". Please talk to the shop staff and mention order #" + order.id + ".";
    } else if (order.status === "cancelled") {
        message = "This order was cancelled.";
    } else {
        message = "Waiting for payment.";
    }

    orderMessage.textContent = message;

    cancelOrderBtn.hidden = !["awaiting_payment", "verifying", "queued"].includes(order.status);
    payAgainBtn.hidden = order.status !== "awaiting_payment";

    // Celebrate while the customer is watching
    if (lastStatus && lastStatus !== "completed" && order.status === "completed") {
        confetti();
        toast("Your prints are ready to collect.");
    }
    if (lastStatus === "verifying" && order.status === "queued") {
        confetti();
        toast("Payment confirmed. Your order is in the queue.");
    }
    if (lastStatus === "verifying" && order.status === "awaiting_payment") {
        toast("We couldn't find your payment", "error");
    }
    lastStatus = order.status;
}

async function refreshOrder() {

    try {

        const order = await api(
            "/api/orders/" + currentOrder.id + "?token=" + encodeURIComponent(currentToken)
        );

        showOrder(order);

        if (["completed", "cancelled"].includes(order.status)) {
            stopTracking();
        }

    } catch (error) {
        console.error("Tracking error:", error);
    }
}

function startTracking() {
    stopTracking();
    trackTimer = setInterval(refreshOrder, 2500);
}

function stopTracking() {
    clearInterval(trackTimer);
    trackTimer = null;
}

cancelOrderBtn.addEventListener("click", async () => {

    if (!confirm("Cancel this order?")) {
        return;
    }

    try {

        const result = await postJson(
            "/api/orders/" + currentOrder.id + "/cancel",
            { token: currentToken }
        );

        showOrder(result.order);
        stopTracking();
        toast("Order cancelled");

    } catch (error) {
        toast(error.message, "error");
        refreshOrder();
    }
});

payAgainBtn.addEventListener("click", () => openPayment(currentOrder));

newOrderBtn.addEventListener("click", () => {

    stopTracking();
    clearTrackedOrder();

    currentOrder = null;
    currentToken = null;
    lastStatus = null;

    orderPanel.hidden = true;
    printCard.hidden = false;

    resetFile();
});

// Resume tracking after a page reload
async function restoreTrackedOrder() {

    let saved = null;

    try {
        saved = JSON.parse(localStorage.getItem(ORDER_STORAGE_KEY));
    } catch {
        return;
    }

    if (!saved || !saved.id || !saved.token) {
        return;
    }

    try {

        const order = await api(
            "/api/orders/" + saved.id + "?token=" + encodeURIComponent(saved.token)
        );

        currentToken = saved.token;
        showOrder(order);

        if (!["completed", "cancelled"].includes(order.status)) {
            startTracking();
        }

    } catch {
        clearTrackedOrder();
    }
}


// ==========================================
// START
// ==========================================

updatePrice();
loadConfig();
restoreTrackedOrder();
