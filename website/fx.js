// ==========================================
// PRINTIFY — interactive motion
// Soft spotlight, ripples, counters, upload sparkle.
// Everything here is decoration: the site works without it.
// ==========================================

(() => {

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)").matches;


    // ==========================================
    // SPARKLE (used by script.js after an upload)
    // ==========================================

    const SPARKLE_COLORS = ["#ff7a3d", "#ffd23f", "#ff7aa2", "#2b1810"];

    window.fxBurst = function (element) {

        if (reduceMotion || !element || !element.animate) {
            return;
        }

        const box = element.getBoundingClientRect();
        const x = box.left + box.width / 2;
        const y = box.top + box.height / 2;
        const count = 14;

        for (let i = 0; i < count; i++) {

            const piece = document.createElement("span");
            piece.className = "burst";
            piece.style.left = x - 3 + "px";
            piece.style.top = y - 3 + "px";
            piece.style.background = SPARKLE_COLORS[i % SPARKLE_COLORS.length];
            document.body.appendChild(piece);

            const angle = (Math.PI * 2 * i) / count + Math.random() * 0.3;
            const distance = 36 + Math.random() * 40;

            piece.animate(
                [
                    { transform: "translate(0, 0) scale(1)", opacity: 0.9 },
                    {
                        transform: `translate(${Math.cos(angle) * distance}px, ${Math.sin(angle) * distance}px) scale(0.2)`,
                        opacity: 0
                    }
                ],
                { duration: 900 + Math.random() * 300, easing: "cubic-bezier(0.22, 1, 0.36, 1)" }
            ).onfinish = () => piece.remove();
        }
    };


    // ==========================================
    // PRICE COUNTERS
    // ==========================================

    const counters = document.querySelectorAll("[data-count]");

    if (!reduceMotion && "IntersectionObserver" in window) {

        const counterObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {

                if (!entry.isIntersecting) {
                    return;
                }

                counterObserver.unobserve(entry.target);

                const element = entry.target;
                const target = Number(element.dataset.count);
                const start = performance.now();

                element.textContent = "₹0";

                function frame(now) {
                    const t = Math.min(1, (now - start) / 1200);
                    const eased = 1 - Math.pow(1 - t, 4);
                    element.textContent = "₹" + Math.round(target * eased);
                    if (t < 1) {
                        requestAnimationFrame(frame);
                    }
                }

                setTimeout(() => requestAnimationFrame(frame), 300);
            });
        }, { threshold: 0.6 });

        counters.forEach((counter) => counterObserver.observe(counter));
    }


    // ==========================================
    // RIPPLES
    // ==========================================

    const RIPPLE_TARGETS = ".pay-btn, .segmented span, .stepper button, .flip-btn, .pay-method span, .secondary-btn, .stage-nav";

    document.addEventListener("pointerdown", (event) => {

        if (reduceMotion) {
            return;
        }

        const target = event.target.closest(RIPPLE_TARGETS) ||
            // Radio labels: the visible chip is the span next to the input
            (event.target.closest(".segmented label, .pay-method") || {}).querySelector?.("span");

        if (!target || target.closest("[disabled]") || target.previousElementSibling?.disabled) {
            return;
        }

        const box = target.getBoundingClientRect();
        const ripple = document.createElement("span");

        ripple.className = "ripple" + (target.matches(".pay-btn") ? "" : " dark");
        ripple.style.left = event.clientX - box.left + "px";
        ripple.style.top = event.clientY - box.top + "px";

        target.appendChild(ripple);
        ripple.addEventListener("animationend", () => ripple.remove());
    });


    // Nothing below makes sense without a mouse
    if (reduceMotion || !finePointer) {
        return;
    }


    // ==========================================
    // SOFT SPOTLIGHT
    // ==========================================

    document.querySelectorAll(".fx-spot").forEach((card) => {

        card.addEventListener("pointerenter", () => {
            // The scroll-reveal delay shouldn't slow down hover
            card.style.transitionDelay = "0s";
        });

        card.addEventListener("pointermove", (event) => {
            const box = card.getBoundingClientRect();
            card.style.setProperty("--mx", ((event.clientX - box.left) / box.width) * 100 + "%");
            card.style.setProperty("--my", ((event.clientY - box.top) / box.height) * 100 + "%");
        });
    });


    // The preview sheet leans gently towards the mouse
    const stage = document.getElementById("stage");
    const sheetStack = document.getElementById("sheetStack");

    if (stage && sheetStack) {

        stage.addEventListener("pointermove", (event) => {
            const box = stage.getBoundingClientRect();
            const x = (event.clientX - box.left) / box.width - 0.5;
            const y = (event.clientY - box.top) / box.height - 0.5;
            sheetStack.style.transform = `rotateY(${x * 5}deg) rotateX(${-y * 4}deg)`;
        });

        stage.addEventListener("pointerleave", () => {
            sheetStack.style.transform = "";
        });
    }

})();
