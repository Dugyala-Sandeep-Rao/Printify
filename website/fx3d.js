// ==========================================
// PRINTIFY — 3D scenes (Three.js)
//
//  * Hero: a sleek printer that quietly prints pages, turns towards the
//    mouse, can be dragged to rotate and tapped to print a page.
//  * Background: soft white pages drifting slowly in depth.
//  * Order tracking: the same printer, reflecting the order status.
//
// Pure decoration: without WebGL (or with reduced motion) the CSS
// versions stay in place.
// ==========================================

import * as THREE from "./vendor/three.module.min.js";

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const smallScreen = window.matchMedia("(max-width: 640px)").matches;

const COLOR = {
    shell: 0xf3f0ea,
    graphite: 0x2b2a31,
    ink: 0x1b1a1f,
    metal: 0xc9c2b6,
    accent: 0xf2601d,
    gold: 0xffc53d,
    green: 0x3fbf86,
    amber: 0xe0a23a,
    red: 0xe0554e,
    off: 0x55525c
};

function webglAvailable() {
    try {
        const canvas = document.createElement("canvas");
        return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
    } catch {
        return false;
    }
}


// ==========================================
// SHARED POINTER
// ==========================================

// Normalised -1..1, y pointing down
const pointer = { x: 0, y: 0, moved: false };

window.addEventListener("pointermove", (event) => {
    pointer.x = (event.clientX / innerWidth) * 2 - 1;
    pointer.y = (event.clientY / innerHeight) * 2 - 1;
    pointer.moved = true;
}, { passive: true });


// ==========================================
// MATERIALS & GEOMETRY HELPERS
// ==========================================

function standard(color, roughness = 0.55, metalness = 0) {
    return new THREE.MeshStandardMaterial({ color, roughness, metalness });
}

function roundedRectShape(width, height, radius) {
    const shape = new THREE.Shape();
    const x = -width / 2;
    const y = -height / 2;
    const r = Math.min(radius, width / 2, height / 2);

    shape.moveTo(x + r, y);
    shape.lineTo(x + width - r, y);
    shape.absarc(x + width - r, y + r, r, -Math.PI / 2, 0, false);
    shape.lineTo(x + width, y + height - r);
    shape.absarc(x + width - r, y + height - r, r, 0, Math.PI / 2, false);
    shape.lineTo(x + r, y + height);
    shape.absarc(x + r, y + height - r, r, Math.PI / 2, Math.PI, false);
    shape.lineTo(x, y + r);
    shape.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5, false);

    return shape;
}

function roundedBox(width, height, depth, radius) {
    const bevel = radius * 0.6;
    const shape = roundedRectShape(width - 2 * bevel, height - 2 * bevel, Math.max(0.01, radius - bevel));

    const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: Math.max(0.01, depth - 2 * bevel),
        bevelEnabled: true,
        bevelSize: bevel,
        bevelThickness: bevel,
        bevelSegments: 5,
        curveSegments: 10
    });

    geometry.center();
    geometry.computeVertexNormals();
    return geometry;
}

// Page texture: white sheet, a fine accent title, soft grey text lines
function pageTexture(variant) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 352;

    const g = canvas.getContext("2d");
    g.fillStyle = "#fdfcfa";
    g.fillRect(0, 0, 256, 352);

    g.fillStyle = variant % 2 ? "#f2601d" : "#ffb13b";
    g.fillRect(28, 36, 90 + (variant * 23) % 50, 7);

    g.fillStyle = "#dcd6cc";
    for (let i = 0; i < 12; i++) {
        g.fillRect(28, 72 + i * 20, 150 + ((i * 41 + variant * 17) % 50), 4);
    }

    g.strokeStyle = "#ebe6de";
    g.lineWidth = 2;
    g.strokeRect(1, 1, 254, 350);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    return texture;
}

const pageTextures = [0, 1, 2, 3].map(pageTexture);

const SHEET_GEOMETRY = new THREE.PlaneGeometry(1.45, 2.0);

function makeSheet(opacity = 1) {
    const material = new THREE.MeshStandardMaterial({
        map: pageTextures[Math.floor(Math.random() * pageTextures.length)],
        roughness: 0.8,
        side: THREE.DoubleSide,
        transparent: true,
        opacity
    });
    return new THREE.Mesh(SHEET_GEOMETRY, material);
}

// Soft round shadow under the printer
function contactShadow(width, depth) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const g = canvas.getContext("2d");
    const gradient = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    gradient.addColorStop(0, "rgba(27, 26, 31, 0.32)");
    gradient.addColorStop(1, "rgba(27, 26, 31, 0)");
    g.fillStyle = gradient;
    g.fillRect(0, 0, 128, 128);

    const texture = new THREE.CanvasTexture(canvas);
    const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(width, depth),
        new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false })
    );
    mesh.rotation.x = -Math.PI / 2;
    return mesh;
}

function addLights(scene) {
    scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d0c4, 1.6));

    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(4, 7, 6);
    scene.add(key);

    const fill = new THREE.DirectionalLight(0xffe4d0, 0.7);
    fill.position.set(-6, 3, 2);
    scene.add(fill);

    const rim = new THREE.DirectionalLight(0xfff1dc, 0.9);
    rim.position.set(0, 4, -6);
    scene.add(rim);
}

function makeRenderer(container) {
    const renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "low-power"
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    container.appendChild(renderer.domElement);
    return renderer;
}


// ==========================================
// RENDER LOOP (only scenes on screen are drawn)
// ==========================================

const scenes = [];

function register(scene, container) {

    scene.active = false;

    new IntersectionObserver((entries) => {
        scene.active = entries[0].isIntersecting;
    }).observe(container);

    new ResizeObserver(() => scene.resize()).observe(container);

    scenes.push(scene);
}

let lastFrame = performance.now();

function frame(now) {
    const dt = Math.min(0.05, (now - lastFrame) / 1000);
    lastFrame = now;

    if (!document.hidden) {
        for (const scene of scenes) {
            if (scene.active) {
                scene.update(dt, now / 1000);
            }
        }
    }

    requestAnimationFrame(frame);
}


// ==========================================
// THE PRINTER
// ==========================================

class Printer3D {

    constructor(container, mode) {

        this.container = container;
        this.mode = mode;                 // "hero" or "order"
        this.status = mode === "hero" ? "demo" : "queued";

        this.renderer = makeRenderer(container);
        this.scene = new THREE.Scene();
        addLights(this.scene);

        this.camera = new THREE.PerspectiveCamera(mode === "hero" ? 32 : 28, 1, 0.1, 100);
        if (mode === "hero") {
            this.camera.position.set(0, 2.6, 9.4);
            this.lookAt = new THREE.Vector3(0, 0.3, 0.6);
        } else {
            this.camera.position.set(0, 2.4, 11);
            this.lookAt = new THREE.Vector3(0, 0.15, 0.7);
        }

        this.root = new THREE.Group();      // lift
        this.turntable = new THREE.Group(); // rotation
        this.root.add(this.turntable);
        this.scene.add(this.root);

        const shadow = contactShadow(5.2, 4.2);
        shadow.position.set(0, -0.8, 0.4);
        this.scene.add(shadow);
        this.shadow = shadow;

        this.buildPrinter();

        this.sheets = [];
        this.stack = [];
        this.spawnTimer = 0.8;
        this.time = 0;

        this.spin = 0;
        this.spinVelocity = 0;
        this.lift = 1;                     // 0..1, 1 = resting
        this.shake = 0;

        this.setupInteraction();
        register(this, container);
    }

    buildPrinter() {

        const t = this.turntable;

        this.shellMaterial = standard(COLOR.shell, 0.5);

        // Main body
        const body = new THREE.Mesh(roundedBox(3.2, 1.15, 2.2, 0.26), this.shellMaterial);
        t.add(body);
        this.body = body;

        // Graphite top unit
        const top = new THREE.Mesh(roundedBox(2.8, 0.42, 1.8, 0.18), standard(COLOR.graphite, 0.38));
        top.position.set(0, 0.74, -0.16);
        t.add(top);

        // Paper waiting in the input tray
        const input = makeSheet();
        input.scale.set(0.88, 0.88, 1);
        input.position.set(0, 1.5, -0.74);
        input.rotation.x = -0.36;
        t.add(input);

        // Fine accent line across the front
        const accentLine = new THREE.Mesh(
            new THREE.BoxGeometry(2.5, 0.025, 0.02),
            new THREE.MeshBasicMaterial({ color: COLOR.accent })
        );
        accentLine.position.set(0, 0.26, 1.1);
        t.add(accentLine);

        // Output slot
        const slot = new THREE.Mesh(roundedBox(2.3, 0.12, 0.16, 0.05), new THREE.MeshBasicMaterial({ color: COLOR.ink }));
        slot.position.set(0, -0.26, 1.06);
        t.add(slot);

        // Output tray
        const tray = new THREE.Mesh(roundedBox(2.4, 0.07, 1.2, 0.04), standard(COLOR.graphite, 0.45));
        tray.position.set(0, -0.56, 1.62);
        t.add(tray);
        this.trayTop = -0.52;

        // Status light: a small glowing pill on the top panel
        this.lightMaterial = new THREE.MeshBasicMaterial({ color: COLOR.green });
        const light = new THREE.Mesh(roundedBox(0.34, 0.06, 0.1, 0.03), this.lightMaterial);
        light.position.set(1.02, 0.97, 0.52);
        t.add(light);

        // Brushed metal buttons
        [0.62, 0.36].forEach((x) => {
            const button = new THREE.Mesh(
                new THREE.CylinderGeometry(0.075, 0.075, 0.05, 28),
                standard(COLOR.metal, 0.3, 0.7)
            );
            button.position.set(x, 0.97, 0.52);
            t.add(button);
        });

        // Small gold brand mark
        const mark = new THREE.Mesh(
            new THREE.CircleGeometry(0.07, 28),
            standard(COLOR.gold, 0.35, 0.8)
        );
        mark.position.set(-1.25, 0.26, 1.105);
        t.add(mark);

        // Feet
        [[-1.3, -0.82], [1.3, -0.82], [-1.3, 0.82], [1.3, 0.82]].forEach(([x, z]) => {
            const foot = new THREE.Mesh(
                new THREE.CylinderGeometry(0.1, 0.12, 0.12, 20),
                standard(COLOR.graphite, 0.6)
            );
            foot.position.set(x, -0.63, z);
            t.add(foot);
        });

        this.root.scale.setScalar(this.mode === "hero" ? 1 : 0.95);
    }

    setupInteraction() {

        if (this.mode !== "hero") {
            return;
        }

        const element = this.container;
        let dragging = false;
        let startX = 0;
        let lastX = 0;
        let moved = 0;

        element.addEventListener("pointerdown", (event) => {
            dragging = true;
            startX = lastX = event.clientX;
            moved = 0;
            element.setPointerCapture(event.pointerId);
            element.classList.add("dragging");
        });

        element.addEventListener("pointermove", (event) => {
            if (!dragging) {
                return;
            }
            const dx = event.clientX - lastX;
            lastX = event.clientX;
            moved += Math.abs(dx);
            this.spinVelocity += dx * 0.12;   // radians per second
        });

        const release = (event) => {
            if (!dragging) {
                return;
            }
            dragging = false;
            element.classList.remove("dragging");

            // A tap (not a drag) prints a page
            if (moved < 6 && Math.abs(event.clientX - startX) < 6) {
                this.lift = 0;
                this.spawnSheet();
            }
        };

        element.addEventListener("pointerup", release);
        element.addEventListener("pointercancel", release);
    }

    setStatus(status) {

        const previous = this.status;
        this.status = status;

        if (status === "completed" && previous !== "completed") {
            this.lift = 0;
            this.spinVelocity += Math.PI * 2 * 1.6;   // one graceful turn
            while (this.stack.length < 3) {
                this.addToStack(this.placeOnTray(makeSheet(), this.stack.length));
            }
        }

        if (status === "failed" && previous !== "failed") {
            this.shake = 1;
        }

        if (["queued", "verifying", "awaiting_payment", "cancelled"].includes(status)) {
            this.stack.forEach((sheet) => this.turntable.remove(sheet));
            this.stack = [];
        }

        this.shellMaterial.color.setHex(status === "cancelled" ? 0xd9d5ce : COLOR.shell);
    }

    placeOnTray(sheet, index) {
        sheet.rotation.set(-Math.PI / 2, 0, (Math.random() - 0.5) * 0.08);
        sheet.position.set((Math.random() - 0.5) * 0.06, this.trayTop + 0.012 + index * 0.02, 1.66);
        sheet.scale.setScalar(0.72);
        this.turntable.add(sheet);
        return sheet;
    }

    addToStack(sheet) {
        this.stack.push(sheet);
        if (this.stack.length > 6) {
            this.turntable.remove(this.stack.shift());
            this.stack.forEach((s, i) => { s.position.y = this.trayTop + 0.012 + i * 0.02; });
        }
    }

    spawnSheet() {
        const sheet = makeSheet();
        sheet.rotation.set(-Math.PI / 2, 0, 0);
        sheet.scale.setScalar(0.72);
        sheet.position.set(0, -0.26, 0.4);
        sheet.userData = { age: 0, phase: "feed", velocity: new THREE.Vector3(), spin: new THREE.Vector3() };
        this.turntable.add(sheet);
        this.sheets.push(sheet);
    }

    updateSheets(dt) {

        for (let i = this.sheets.length - 1; i >= 0; i--) {

            const sheet = this.sheets[i];
            const data = sheet.userData;
            data.age += dt;

            if (data.phase === "feed") {
                // Glide out of the slot onto the tray
                const t = Math.min(1, data.age / 1.4);
                const eased = 1 - Math.pow(1 - t, 3);
                sheet.position.z = 0.4 + eased * 1.26;
                sheet.position.y = -0.26 + (this.trayTop + 0.02 + 0.26) * eased;

                if (t >= 1) {
                    if (this.mode === "order") {
                        this.sheets.splice(i, 1);
                        this.turntable.remove(sheet);
                        this.addToStack(this.placeOnTray(sheet, this.stack.length));
                        continue;
                    }
                    data.phase = "float";
                    data.age = 0;
                    data.velocity.set((Math.random() - 0.5) * 0.6, 1.1 + Math.random() * 0.4, 0.35 + Math.random() * 0.3);
                    data.spin.set((Math.random() - 0.5) * 1.2, (Math.random() - 0.5) * 1.4, (Math.random() - 0.5) * 1.0);
                }
                continue;
            }

            // Drift up and away, like a page caught by a breeze
            data.velocity.y *= 0.992;
            sheet.position.addScaledVector(data.velocity, dt);
            sheet.position.x += Math.sin(data.age * 2.2 + i) * 0.006;
            sheet.rotation.x += data.spin.x * dt;
            sheet.rotation.y += data.spin.y * dt;
            sheet.rotation.z += data.spin.z * dt;

            const life = 3.6;
            if (data.age > life - 1.4) {
                sheet.material.opacity = Math.max(0, (life - data.age) / 1.4);
            }

            if (data.age > life) {
                this.turntable.remove(sheet);
                sheet.material.dispose();
                this.sheets.splice(i, 1);
            }
        }
    }

    resize() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        if (!width || !height) {
            return;
        }
        this.renderer.setSize(width, height);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.camera.lookAt(this.lookAt);
    }

    update(dt) {

        if (!this.container.clientWidth) {
            return;
        }

        this.time += dt;
        const t = this.time;
        const status = this.status;

        // --- Turning -------------------------------------------------
        this.spin += this.spinVelocity * dt;
        this.spinVelocity *= Math.pow(0.2, dt);

        // Settle facing forward once the spin slows down
        if (Math.abs(this.spinVelocity) < 0.4) {
            const facing = Math.round(this.spin / (Math.PI * 2)) * Math.PI * 2;
            this.spin += (facing - this.spin) * Math.min(1, dt * 2);
        }

        let targetY;
        let targetX = 0;

        if (this.mode === "hero") {
            targetY = pointer.moved ? -0.25 + pointer.x * 0.35 : -0.25 + Math.sin(t * 0.35) * 0.3;
            targetX = pointer.moved ? pointer.y * 0.06 : 0;
        } else {
            targetY = -0.2 + Math.sin(t * 0.4) * 0.22;
        }

        const turn = this.turntable.rotation;
        turn.y += (targetY + this.spin - turn.y) * Math.min(1, dt * 3);
        turn.x += (targetX - turn.x) * Math.min(1, dt * 3);

        // --- Float, lift and shake --------------------------------------
        let y = Math.sin(t * 1.4) * 0.03;

        if (this.lift < 1) {
            this.lift = Math.min(1, this.lift + dt * 1.2);
            y += Math.sin(Math.PI * this.lift) * 0.22;
        }

        this.root.position.y = y;
        this.shadow.material.opacity = 1 - y * 1.4;
        this.shadow.scale.setScalar(1 - y * 0.4);

        const printing = status === "printing" || status === "demo";
        const vibrate = status === "printing" ? 0.006 : 0;
        const shake = this.shake > 0 ? 0.03 * this.shake : 0;
        this.body.position.x = Math.sin(t * 60) * (vibrate + shake);
        this.shake = Math.max(0, this.shake - dt * 1.2);

        // --- Printing ---------------------------------------------------
        if (printing) {
            this.spawnTimer -= dt;
            if (this.spawnTimer <= 0) {
                this.spawnSheet();
                this.spawnTimer = status === "demo" ? 2.6 : 1.6;
            }
        }
        this.updateSheets(dt);

        // --- Status light -----------------------------------------------
        let color = COLOR.green;
        let pulse = 0;

        if (status === "queued" || status === "verifying" || status === "awaiting_payment") {
            color = COLOR.amber;
            pulse = 1.6;
        } else if (printing) {
            color = COLOR.green;
            pulse = status === "printing" ? 4 : 1.2;
        } else if (status === "failed") {
            color = COLOR.red;
            pulse = 2.4;
        } else if (status === "cancelled") {
            color = COLOR.off;
        }

        this.lightMaterial.color.setHex(color);
        if (pulse) {
            this.lightMaterial.color.multiplyScalar(0.55 + 0.45 * (0.5 + 0.5 * Math.sin(t * pulse * Math.PI)));
        }

        this.renderer.render(this.scene, this.camera);
    }
}


// ==========================================
// BACKGROUND PAGES
// ==========================================

class PaperField {

    constructor(container) {

        this.container = container;
        this.renderer = makeRenderer(container);
        this.scene = new THREE.Scene();
        addLights(this.scene);

        this.camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
        this.camera.position.set(0, 0, 10);

        this.field = new THREE.Group();
        this.scene.add(this.field);

        const count = smallScreen ? 6 : 10;
        this.papers = [];

        for (let i = 0; i < count; i++) {

            const z = -10 + Math.random() * 8;
            const paper = makeSheet((smallScreen ? 0.14 : 0.24) * (0.5 + 0.5 * ((z + 10) / 8)));

            paper.position.set((Math.random() * 2 - 1) * 12, (Math.random() * 2 - 1) * 7, z);
            paper.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, Math.random() * Math.PI);
            paper.scale.setScalar(0.6 + Math.random() * 0.4);
            paper.material.depthWrite = false;

            paper.userData = {
                rise: 0.08 + Math.random() * 0.14,
                spin: new THREE.Vector3((Math.random() - 0.5) * 0.25, (Math.random() - 0.5) * 0.3, (Math.random() - 0.5) * 0.2),
                sway: Math.random() * Math.PI * 2
            };

            this.field.add(paper);
            this.papers.push(paper);
        }

        register(this, container);
    }

    resize() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;
        this.renderer.setSize(width, height);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    }

    update(dt, now) {

        // Gentle mouse parallax and scroll depth
        this.camera.position.x += (pointer.x * 0.6 - this.camera.position.x) * Math.min(1, dt * 1.5);
        this.camera.position.y += (-pointer.y * 0.4 - this.camera.position.y) * Math.min(1, dt * 1.5);
        this.camera.lookAt(0, 0, 0);

        const scrollShift = window.scrollY * 0.003;

        for (const paper of this.papers) {

            const data = paper.userData;
            paper.position.y += data.rise * dt;
            paper.position.x += Math.sin(now * 0.3 + data.sway) * 0.002;
            paper.rotation.x += data.spin.x * dt;
            paper.rotation.y += data.spin.y * dt;
            paper.rotation.z += data.spin.z * dt;

            const worldY = paper.position.y + scrollShift;
            if (worldY > 8.5) {
                paper.position.y -= 17;
            } else if (worldY < -8.5) {
                paper.position.y += 17;
            }
        }

        this.field.position.y = scrollShift;

        this.renderer.render(this.scene, this.camera);
    }
}


// ==========================================
// START
// ==========================================

function start() {

    const blobs = document.querySelector(".blobs");
    if (blobs) {
        const layer = document.createElement("div");
        layer.className = "bg-3d";
        blobs.appendChild(layer);
        new PaperField(layer);
    }

    const hero = document.getElementById("hero3d");
    if (hero) {
        new Printer3D(hero, "hero");
    }

    // Order tracking printer, driven by the status script.js sets
    const orderScene = document.getElementById("printerScene");
    if (orderScene) {
        const holder = document.createElement("div");
        holder.className = "scene-3d";
        orderScene.appendChild(holder);

        const printer = new Printer3D(holder, "order");
        const sync = () => printer.setStatus(orderScene.dataset.status || "queued");

        new MutationObserver(sync).observe(orderScene, {
            attributes: true,
            attributeFilter: ["data-status"]
        });
        sync();
    }

    document.documentElement.classList.add("has-3d");
    requestAnimationFrame(frame);
}

if (!reduceMotion && webglAvailable()) {
    try {
        start();
    } catch (error) {
        console.warn("3D disabled:", error);
        document.documentElement.classList.remove("has-3d");
    }
}
