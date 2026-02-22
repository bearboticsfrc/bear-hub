/**
 * BearHub Dashboard — Team 4068
 * Vanilla JS, no framework.
 */

// ── Score chart ───────────────────────────────────────────────────────────────

class ScoreChart {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.history = []; // [{t: Date, v: number}]
        this.WINDOW_MS = (2 * 60 + 40) * 1000; // 2m 40s — one FRC match

        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this._resize();
        window.addEventListener('resize', () => this._resize());
        this._animate();
    }

    _resize() {
        if (!this.canvas) return;
        this.canvas.width  = this.canvas.offsetWidth  * devicePixelRatio;
        this.canvas.height = this.canvas.offsetHeight * devicePixelRatio;
    }

    _animate() {
        this.draw();
        requestAnimationFrame(() => this._animate());
    }

    push(value) {
        if (!this.canvas) return;
        const now = Date.now();
        this.history.push({ t: now, v: value });
        const cutoff = now - this.WINDOW_MS;
        this.history = this.history.filter(p => p.t >= cutoff);
    }

    draw() {
        if (!this.canvas || !this.ctx) return;
        const { width: W, height: H } = this.canvas;
        const ctx = this.ctx;
        ctx.clearRect(0, 0, W, H);

        const PAD = { top: 10, right: 10, bottom: Math.ceil(20 * devicePixelRatio), left: 40 };
        const gW = W - PAD.left - PAD.right;
        const gH = H - PAD.top  - PAD.bottom;

        if (this.history.length < 2) {
            // Not enough data yet — draw empty axes
            this._drawAxes(ctx, PAD, gW, gH, W, H, 0);
            return;
        }

        const now    = Date.now();
        const tMin   = now - this.WINDOW_MS;
        const maxVal = Math.max(...this.history.map(p => p.v), 10);
        const yMax   = Math.ceil(maxVal * 1.15 / 10) * 10; // round up to nearest 10

        const xOf = t => PAD.left + ((t - tMin) / this.WINDOW_MS) * gW;
        const yOf = v => PAD.top  + gH - (v / yMax) * gH;

        // Gradient fill under the line
        const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
        grad.addColorStop(0,   'rgba(68, 136, 255, 0.35)');
        grad.addColorStop(1,   'rgba(68, 136, 255, 0.02)');

        ctx.beginPath();
        ctx.moveTo(xOf(this.history[0].t), yOf(this.history[0].v));
        for (let i = 1; i < this.history.length; i++) {
            ctx.lineTo(xOf(this.history[i].t), yOf(this.history[i].v));
        }
        ctx.lineTo(xOf(this.history.at(-1).t), PAD.top + gH);
        ctx.lineTo(xOf(this.history[0].t),     PAD.top + gH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        // Line
        ctx.beginPath();
        ctx.moveTo(xOf(this.history[0].t), yOf(this.history[0].v));
        for (let i = 1; i < this.history.length; i++) {
            ctx.lineTo(xOf(this.history[i].t), yOf(this.history[i].v));
        }
        ctx.strokeStyle = '#4488FF';
        ctx.lineWidth   = 2 * devicePixelRatio;
        ctx.lineJoin    = 'round';
        ctx.stroke();

        this._drawAxes(ctx, PAD, gW, gH, W, H, yMax);
    }

    _drawAxes(ctx, PAD, gW, gH, W, H, yMax) {
        const dpr = devicePixelRatio;
        ctx.strokeStyle = 'rgba(136, 153, 187, 0.25)';
        ctx.lineWidth   = dpr;
        ctx.font        = `${11 * dpr}px system-ui, sans-serif`;
        ctx.fillStyle   = 'rgba(136, 153, 187, 0.7)';
        ctx.textAlign   = 'right';

        // Y gridlines + labels (0, mid, max)
        [0, 0.5, 1].forEach(frac => {
            const y = PAD.top + gH - frac * gH;
            const v = Math.round(frac * yMax);
            ctx.beginPath();
            ctx.moveTo(PAD.left, y);
            ctx.lineTo(PAD.left + gW, y);
            ctx.stroke();
            ctx.fillText(v, PAD.left - 4 * dpr, y + 4 * dpr);
        });

        // X labels (now-5m, now-2.5m, now)
        ctx.textAlign = 'center';
        [['−2m40s', 0], ['−1m20s', 0.5], ['now', 1]].forEach(([label, frac]) => {
            const x = PAD.left + frac * gW;
            ctx.fillText(label, x, PAD.top + gH + 16 * dpr);
        });
    }
}

// ── Main app ─────────────────────────────────────────────────────────────────

class BearHubApp {
    constructor() {
        this.ws = null;
        this.reconnectTimer = null;
        this.keepaliveTimer = null;
        this.previousActive = 0;
        this.milestonesFired = new Set(); // 'energized' | 'supercharged'
        this.isInitialState = true; // suppress animations on first state message

        // Thresholds (match server config.py)
        this.THRESHOLD_ENERGIZED    = 100;
        this.THRESHOLD_SUPERCHARGED = 360;

        this.chart = new ScoreChart('score-chart');

        this.init();
    }

    init() {
        this.setupConfetti();
        this.bindResetButton();
        this.connectWebSocket();
    }

    // ── WebSocket ──────────────────────────────────────────────────────────

    connectWebSocket() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${proto}//${location.host}/api/ws`);

        this.ws.onopen = () => {
            console.log('WS connected');
            if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
            this.startKeepalive();
        };

        this.ws.onmessage = (evt) => {
            if (evt.data === 'pong') return;
            try {
                const msg = JSON.parse(evt.data);
                if (msg.type === 'state') this.updateState(msg.data);
            } catch (e) {
                console.error('WS parse error', e);
            }
        };

        this.ws.onclose = () => {
            console.log('WS disconnected');
            this.stopKeepalive();
            this.scheduleReconnect();
        };

        this.ws.onerror = (e) => console.error('WS error', e);
    }

    startKeepalive() {
        this.keepaliveTimer = setInterval(() => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send('ping');
            }
        }, 30000);
    }

    stopKeepalive() {
        if (this.keepaliveTimer) { clearInterval(this.keepaliveTimer); this.keepaliveTimer = null; }
    }

    scheduleReconnect() {
        if (!this.reconnectTimer) {
            this.reconnectTimer = setTimeout(() => {
                this.reconnectTimer = null;
                this.connectWebSocket();
            }, 5000);
        }
    }

    // ── State update ──────────────────────────────────────────────────────

    updateState(data) {
        // Hub name
        const hubBadge = document.getElementById('hub-name-badge');
        if (hubBadge && data.hub_name) hubBadge.textContent = data.hub_name;

        // Mode badge
        const modeBadge = document.getElementById('mode-badge');
        if (modeBadge) {
            modeBadge.textContent = data.mode || 'demo';
            modeBadge.className = `mode-badge mode-${data.mode || 'demo'}`;
        }

        // Status dots — highlight the relevant one for the current mode
        const fmsDot  = document.getElementById('fms-dot');
        const ntDot   = document.getElementById('nt-dot');
        const fmsItem = fmsDot  && fmsDot.closest('.status-item');
        const ntItem  = ntDot   && ntDot.closest('.status-item');

        const sacnDot  = document.getElementById('sacn-dot');
        const sacnItem = sacnDot && sacnDot.closest('.status-item');

        if (fmsDot)  fmsDot.classList.toggle('connected',  !!data.modbus_active);
        if (ntDot)   ntDot.classList.toggle('connected',   !!data.nt_connected);
        if (sacnDot) sacnDot.classList.toggle('connected', !!data.sacn_active);

        const mode = data.mode || 'demo';
        if (fmsItem)  fmsItem.classList.toggle('active-mode', mode === 'fms');
        if (ntItem)   ntItem.classList.toggle('active-mode',  mode === 'robot_teleop' || mode === 'robot_practice');
        if (sacnItem) sacnItem.classList.toggle('active-mode', mode === 'fms');

        // Admin page status mirrors
        const aFmsDot  = document.getElementById('admin-fms-dot');
        const aNtDot   = document.getElementById('admin-nt-dot');
        const aFmsTxt  = document.getElementById('admin-fms-text');
        const aNtTxt   = document.getElementById('admin-nt-text');
        const aSacnDot = document.getElementById('admin-sacn-dot');
        const aSacnTxt = document.getElementById('admin-sacn-text');
        if (aFmsDot)  aFmsDot.classList.toggle('connected',  !!data.modbus_active);
        if (aNtDot)   aNtDot.classList.toggle('connected',   !!data.nt_connected);
        if (aSacnDot) aSacnDot.classList.toggle('connected', !!data.sacn_active);
        if (aFmsTxt)  aFmsTxt.textContent  = data.modbus_active ? 'Connected' : 'Disconnected';
        if (aNtTxt)   aNtTxt.textContent   = data.nt_connected  ? 'Connected' : 'Disconnected';
        if (aSacnTxt) aSacnTxt.textContent = data.sacn_active   ? 'Active'    : 'No signal';

        // Active mode button highlight (admin page)
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Counts
        const active   = data.active_count   ?? 0;
        const autoC    = data.auto_count     ?? 0;
        const inactive = data.inactive_count ?? 0;

        this.setCount('active-count', active);
        this.setCount('auto-count',   autoC);
        this.setCount('inactive-count', inactive);

        this.chart.push(active);

        // Admin page counts
        this.setTextIfExists('adm-active',   active);
        this.setTextIfExists('adm-auto',     autoC);
        this.setTextIfExists('adm-inactive', inactive);

        // Threshold color on active count
        const activeEl = document.getElementById('active-count');
        if (activeEl) {
            activeEl.classList.toggle('supercharged', active >= this.THRESHOLD_SUPERCHARGED);
            activeEl.classList.toggle('energized',    active >= this.THRESHOLD_ENERGIZED && active < this.THRESHOLD_SUPERCHARGED);
        }

        if (this.isInitialState) {
            // Seed state from server without triggering animations —
            // the threshold was already crossed before this page load.
            if (active >= this.THRESHOLD_SUPERCHARGED) {
                this.milestonesFired.add('supercharged');
                this.milestonesFired.add('energized');
            } else if (active >= this.THRESHOLD_ENERGIZED) {
                this.milestonesFired.add('energized');
            }
            this.isInitialState = false;
        } else {
            // Only animate for crossings that happen live on this page.
            this.checkThresholds(this.previousActive, active);
        }
        this.previousActive = active;

        // Reset button visibility
        const resetSection = document.getElementById('reset-section');
        if (resetSection) resetSection.style.display = (mode === 'demo') ? '' : 'none';

        // Simulator button visibility
        const simBtn = document.getElementById('simulate-btn');
        if (simBtn) simBtn.style.display = data.simulator_enabled ? '' : 'none';

        // Simulator toggle (admin page)
        const simToggle = document.getElementById('simulator-toggle');
        if (simToggle) simToggle.checked = !!data.simulator_enabled;

        // Motors button (dashboard) — always visible; label reflects state
        const motorsBtn = document.getElementById('motors-btn');
        if (motorsBtn) {
            const running = !!data.motors_running;
            motorsBtn.style.display = '';
            motorsBtn.textContent = running ? 'Stop Motors' : 'Start Motors';
            motorsBtn.classList.toggle('motors-stop', running);
            motorsBtn.classList.toggle('motors-start', !running);
        }

        // Motors toggle (admin page)
        const motorsToggle = document.getElementById('motors-toggle');
        if (motorsToggle) motorsToggle.checked = !!data.motors_running;

        // Period badge (both pages) — visible only in robot modes
        const periodBadge = document.getElementById('period-badge');
        if (periodBadge) {
            const inRobotMode = mode === 'robot_teleop' || mode === 'robot_practice';
            periodBadge.style.display = inRobotMode ? '' : 'none';
            if (inRobotMode) {
                const period = data.fms_period || 'disabled';
                periodBadge.textContent = period;
                periodBadge.className = `period-badge period-${period}`;
            }
        }

        // Countdown (dashboard only)
        const countdownDisplay = document.getElementById('countdown-display');
        const countdownSeconds = document.getElementById('countdown-seconds');
        if (countdownDisplay) {
            const showCountdown = mode === 'robot_practice' && data.seconds_until_inactive >= 0;
            countdownDisplay.style.display = showCountdown ? '' : 'none';
            if (showCountdown && countdownSeconds) {
                countdownSeconds.textContent = Math.max(0, Math.ceil(data.seconds_until_inactive));
            }
        }

        // NT server address (admin page) — only update if field is not focused
        const ntInput = document.getElementById('nt-address-input');
        if (ntInput && document.activeElement !== ntInput && data.nt_server_address) {
            ntInput.value = data.nt_server_address;
        }
    }

    setCount(id, value) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.textContent !== String(value)) {
            el.textContent = value;
            el.classList.remove('pulse');
            void el.offsetWidth; // reflow to restart animation
            el.classList.add('pulse');
            setTimeout(() => el.classList.remove('pulse'), 400);
        }
    }

    setTextIfExists(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    // ── Thresholds & milestone animations ────────────────────────────────

    checkThresholds(prev, current) {
        if (prev < this.THRESHOLD_SUPERCHARGED && current >= this.THRESHOLD_SUPERCHARGED) {
            if (!this.milestonesFired.has('supercharged')) {
                this.milestonesFired.add('supercharged');
                this.triggerMilestone('supercharged');
            }
        } else if (prev < this.THRESHOLD_ENERGIZED && current >= this.THRESHOLD_ENERGIZED) {
            if (!this.milestonesFired.has('energized')) {
                this.milestonesFired.add('energized');
                this.triggerMilestone('energized');
            }
        }
    }

    triggerMilestone(type) {
        const isSupercharged = type === 'supercharged';

        // Screen flash
        const flash = document.createElement('div');
        flash.className = `milestone-flash ${type}`;
        document.body.appendChild(flash);
        setTimeout(() => flash.remove(), 600);

        // Screen shake
        document.body.classList.add(isSupercharged ? 'shake-intense' : 'shake');
        setTimeout(() => document.body.classList.remove('shake', 'shake-intense'),
            isSupercharged ? 2100 : 800);

        // Confetti
        this.launchConfetti(isSupercharged ? 350 : 160, type);
    }

    // ── Confetti ──────────────────────────────────────────────────────────

    setupConfetti() {
        this.confettiCanvas = document.getElementById('confetti-canvas');
        if (!this.confettiCanvas) return;
        this.confettiCtx = this.confettiCanvas.getContext('2d');
        this.confettiParticles = [];
        this.confettiRunning = false;
        this.resizeConfetti();
        window.addEventListener('resize', () => this.resizeConfetti());
    }

    resizeConfetti() {
        if (!this.confettiCanvas) return;
        this.confettiCanvas.width  = window.innerWidth;
        this.confettiCanvas.height = window.innerHeight;
    }

    launchConfetti(count, type) {
        if (!this.confettiCanvas) return;
        const colors = type === 'supercharged'
            ? ['#00CFFF', '#0099CC', '#66E5FF', '#FFFFFF', '#88DDFF']
            : ['#FFB300', '#FFD700', '#FFA500', '#FFEC8B', '#FFFFFF'];

        for (let i = 0; i < count; i++) {
            this.confettiParticles.push({
                x: Math.random() * this.confettiCanvas.width,
                y: -20 - Math.random() * 80,
                vx: (Math.random() - 0.5) * 14,
                vy: Math.random() * 3 + 2,
                size: Math.random() * 10 + 5,
                color: colors[Math.floor(Math.random() * colors.length)],
                rotation: Math.random() * 360,
                rotSpeed: (Math.random() - 0.5) * 12,
                shape: Math.random() > 0.5 ? 'rect' : 'circle',
                gravity: 0.13 + Math.random() * 0.1,
                drag: 0.98 + Math.random() * 0.01,
                wobble: Math.random() * Math.PI * 2,
                wobbleSpeed: 0.04 + Math.random() * 0.08,
            });
        }

        if (!this.confettiRunning) {
            this.confettiRunning = true;
            this.animateConfetti();
        }
    }

    animateConfetti() {
        const ctx = this.confettiCtx;
        ctx.clearRect(0, 0, this.confettiCanvas.width, this.confettiCanvas.height);

        this.confettiParticles = this.confettiParticles.filter(p => {
            p.vy += p.gravity;
            p.vx *= p.drag;
            p.vy *= p.drag;
            p.x  += p.vx + Math.sin(p.wobble) * 1.5;
            p.y  += p.vy;
            p.rotation  += p.rotSpeed;
            p.wobble += p.wobbleSpeed;

            ctx.save();
            ctx.translate(p.x, p.y);
            ctx.rotate(p.rotation * Math.PI / 180);
            ctx.fillStyle = p.color;

            if (p.shape === 'rect') {
                ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
            } else {
                ctx.beginPath();
                ctx.arc(0, 0, p.size / 2, 0, Math.PI * 2);
                ctx.fill();
            }
            ctx.restore();

            return p.y < this.confettiCanvas.height + 60;
        });

        if (this.confettiParticles.length > 0) {
            requestAnimationFrame(() => this.animateConfetti());
        } else {
            this.confettiRunning = false;
        }
    }

    // ── Reset / Motors buttons ────────────────────────────────────────────

    bindResetButton() {
        const motorsBtn = document.getElementById('motors-btn');
        if (motorsBtn) {
            motorsBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/motors/toggle', { method: 'POST' });
                } catch (e) {
                    this.showToast('Motor toggle failed', 'error');
                }
            });
        }

        const btn = document.getElementById('reset-btn');
        if (btn) {
            btn.addEventListener('click', async () => {
                try {
                    await fetch('/api/counts/reset', { method: 'POST' });
                    this.milestonesFired.clear();
                    this.previousActive = 0;
                    this.chart.history = [];
                    this.showToast('Counts reset', 'success');
                } catch (e) {
                    this.showToast('Reset failed', 'error');
                }
            });
        }

        const simBtn = document.getElementById('simulate-btn');
        if (simBtn) {
            let holdState = null;

            const fire = () => fetch('/api/simulate/ball', { method: 'POST' });

            const startHold = (e) => {
                e.preventDefault();
                fire();
                let delay = 250;
                const scheduleNext = () => {
                    holdState = setTimeout(() => {
                        if (holdState === null) return;
                        fire();
                        delay = Math.max(50, delay * 0.85); // ramp up to ~20/s
                        scheduleNext();
                    }, delay);
                };
                scheduleNext();
            };

            const stopHold = () => { clearTimeout(holdState); holdState = null; };

            simBtn.addEventListener('mousedown', startHold);
            simBtn.addEventListener('mouseup', stopHold);
            simBtn.addEventListener('mouseleave', stopHold);
            simBtn.addEventListener('touchstart', startHold, { passive: false });
            simBtn.addEventListener('touchend', stopHold);
        }
    }

    // ── Toast ─────────────────────────────────────────────────────────────

    showToast(message, type = 'info') {
        document.querySelectorAll('.toast').forEach(t => t.remove());
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.app = new BearHubApp();
});
