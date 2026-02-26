import { useEffect, useRef } from 'react';

interface GraphNode {
    x: number;
    y: number;
    radius: number;
}

interface GraphEdge {
    from: number;
    to: number;
}

interface WorkflowNode {
    x: number;
    y: number;
    size: number;
    status: 'pending' | 'running' | 'done' | 'error';
}

interface OrganicScene {
    mode: 'organic';
    start: number;
    duration: number;
    nodes: GraphNode[];
    edges: GraphEdge[];
    hue: number;
    family: 'navy' | 'amber' | 'trust';
}

interface WorkflowScene {
    mode: 'workflow';
    start: number;
    duration: number;
    nodes: WorkflowNode[];
    edges: GraphEdge[];
    hue: number;
}

type Scene = OrganicScene | WorkflowScene;
type RGB = readonly [number, number, number];

interface AuthGraphBackgroundProps {
    loginState?: 'idle' | 'verifying' | 'success' | 'error';
}

function clamp(value: number, min: number, max: number) {
    return Math.max(min, Math.min(max, value));
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

type Point = { x: number; y: number };

function bezierPoint(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
    const mt = 1 - t;
    const mt2 = mt * mt;
    const t2 = t * t;
    const a = mt2 * mt;
    const b = 3 * mt2 * t;
    const c = 3 * mt * t2;
    const d = t * t2;
    return {
        x: a * p0.x + b * p1.x + c * p2.x + d * p3.x,
        y: a * p0.y + b * p1.y + c * p2.y + d * p3.y,
    };
}

function smoothStepControls(from: Point, to: Point): [Point, Point] {
    const dx = to.x - from.x;
    const distance = Math.abs(dx);
    const offset = clamp(distance * 0.45, 26, 92);
    return [
        { x: from.x + offset, y: from.y },
        { x: to.x - offset, y: to.y },
    ];
}

function rgba([r, g, b]: RGB, alpha: number) {
    return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1).toFixed(3)})`;
}

function pickHueFamily(): { hue: number; family: 'navy' | 'amber' | 'trust' } {
    const roll = Math.random();
    if (roll < 0.6) return { hue: 210 + Math.random() * 20, family: 'navy' };
    if (roll < 0.8) return { hue: 30 + Math.random() * 10, family: 'amber' };
    return { hue: 165 + Math.random() * 10, family: 'trust' };
}

export function AuthGraphBackground({ loginState = 'idle' }: AuthGraphBackgroundProps) {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const context = canvas.getContext('2d');
        if (!context) return;

        const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        const scenes: Scene[] = [];
        let lastSpawn = 0;
        let raf = 0;
        let spawnWorkflowNext = true;

        const resize = () => {
            const dpr = window.devicePixelRatio || 1;
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            canvas.width = Math.floor(width * dpr);
            canvas.height = Math.floor(height * dpr);
            context.setTransform(dpr, 0, 0, dpr, 0, 0);
        };

        const createOrganicScene = (time: number): OrganicScene => {
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            const nodesCount = Math.floor(4 + Math.random() * 4);
            const nodes: GraphNode[] = [];

            for (let i = 0; i < nodesCount; i += 1) {
                nodes.push({
                    x: width * (0.12 + Math.random() * 0.76),
                    y: height * (0.12 + Math.random() * 0.76),
                    radius: 1.5 + Math.random() * 2.5,
                });
            }

            const edges: GraphEdge[] = [];
            for (let i = 1; i < nodes.length; i += 1) {
                edges.push({ from: i - 1, to: i });
                if (i > 1 && Math.random() > 0.6) {
                    edges.push({ from: i, to: Math.floor(Math.random() * i) });
                }
            }

            const hueData = pickHueFamily();
            return {
                mode: 'organic',
                start: time,
                duration: 5200 + Math.random() * 1800,
                nodes,
                edges,
                hue: hueData.hue,
                family: hueData.family,
            };
        };

        const createWorkflowScene = (time: number): WorkflowScene => {
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            const centerX = width * (0.22 + Math.random() * 0.56);
            const centerY = height * (0.24 + Math.random() * 0.52);
            const spacing = 64 + Math.random() * 22;
            const size = 10 + Math.random() * 3;
            const pattern = Math.floor(Math.random() * 3);

            const nodes: WorkflowNode[] = [];
            const edges: GraphEdge[] = [];

            if (pattern === 0) {
                nodes.push(
                    { x: centerX - spacing * 1.15, y: centerY, size, status: 'running' },
                    { x: centerX - spacing * 0.25, y: centerY, size, status: 'pending' },
                    { x: centerX + spacing * 0.7, y: centerY - spacing * 0.55, size, status: 'done' },
                    { x: centerX + spacing * 0.7, y: centerY + spacing * 0.55, size, status: 'pending' },
                );
                edges.push({ from: 0, to: 1 }, { from: 1, to: 2 }, { from: 1, to: 3 });
            } else if (pattern === 1) {
                nodes.push(
                    { x: centerX, y: centerY - spacing * 1.2, size, status: 'done' },
                    { x: centerX, y: centerY - spacing * 0.25, size, status: 'running' },
                    { x: centerX, y: centerY + spacing * 0.7, size, status: 'pending' },
                    { x: centerX + spacing * 0.9, y: centerY + spacing * 0.7, size, status: 'pending' },
                );
                edges.push({ from: 0, to: 1 }, { from: 1, to: 2 }, { from: 2, to: 3 });
            } else {
                nodes.push(
                    { x: centerX - spacing * 1.35, y: centerY + spacing * 0.35, size, status: 'done' },
                    { x: centerX - spacing * 0.45, y: centerY, size, status: 'running' },
                    { x: centerX + spacing * 0.45, y: centerY, size, status: 'error' },
                    { x: centerX + spacing * 1.35, y: centerY - spacing * 0.35, size, status: 'pending' },
                );
                edges.push({ from: 0, to: 1 }, { from: 1, to: 2 }, { from: 2, to: 3 });
            }

            const hueData = pickHueFamily();
            return {
                mode: 'workflow',
                start: time,
                duration: 5600 + Math.random() * 1600,
                nodes,
                edges,
                hue: hueData.hue,
            };
        };

        const drawDotGrid = (alpha = 0.18) => {
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            const gap = 24;
            context.fillStyle = `rgba(120, 132, 156, ${alpha})`;
            for (let x = 10; x < width; x += gap) {
                for (let y = 10; y < height; y += gap) {
                    context.fillRect(x, y, 1.1, 1.1);
                }
            }
        };

        const drawStatic = () => {
            const width = canvas.clientWidth;
            const height = canvas.clientHeight;
            context.clearRect(0, 0, width, height);
            context.fillStyle = '#080c14';
            context.fillRect(0, 0, width, height);
            drawDotGrid(0.16);
        };

        const drawOrganicScene = (scene: OrganicScene, now: number) => {
            const progress = clamp((now - scene.start) / scene.duration, 0, 1);
            const intro = clamp(progress / 0.22, 0, 1);
            const outro = progress > 0.74 ? clamp((1 - progress) / 0.26, 0, 1) : 1;
            const alpha = intro * outro;

            const edgeReveal = clamp((progress - 0.05) / 0.3, 0, 1);
            const pulse = clamp((progress - 0.25) / 0.5, 0, 1);

            for (const edge of scene.edges) {
                const from = scene.nodes[edge.from];
                const to = scene.nodes[edge.to];
                const dx = to.x - from.x;
                const dy = to.y - from.y;

                context.beginPath();
                context.moveTo(from.x, from.y);
                context.lineTo(from.x + dx * edgeReveal, from.y + dy * edgeReveal);
                context.strokeStyle = `hsla(${scene.hue}, 88%, 68%, ${0.12 * alpha})`;
                context.lineWidth = 1;
                context.stroke();

                if (pulse > 0 && edgeReveal > 0.95) {
                    const t = (pulse * 1.15 + (edge.from * 0.17)) % 1;
                    const px = from.x + dx * t;
                    const py = from.y + dy * t;
                    context.beginPath();
                    context.arc(px, py, 2.1, 0, Math.PI * 2);
                    context.fillStyle = `hsla(${scene.hue + 8}, 95%, 74%, ${0.62 * alpha})`;
                    context.fill();
                }
            }

            for (let i = 0; i < scene.nodes.length; i += 1) {
                const node = scene.nodes[i];
                const breathing = 0.92 + Math.sin(now * 0.002 + i * 0.8) * 0.08;
                const radius = node.radius * breathing;

                context.beginPath();
                context.arc(node.x, node.y, radius, 0, Math.PI * 2);
                context.fillStyle = `hsla(${scene.hue}, 90%, 74%, ${0.5 * alpha})`;
                context.fill();

                context.beginPath();
                context.arc(node.x, node.y, radius * 2.8, 0, Math.PI * 2);
                context.fillStyle = `hsla(${scene.hue}, 95%, 65%, ${0.1 * alpha})`;
                context.fill();
            }
        };

        const drawWorkflowScene = (scene: WorkflowScene, now: number) => {
            const progress = clamp((now - scene.start) / scene.duration, 0, 1);
            const intro = clamp(progress / 0.18, 0, 1);
            const outro = progress > 0.76 ? clamp((1 - progress) / 0.24, 0, 1) : 1;
            const alpha = intro * outro;

            const sequence = clamp((progress - 0.08) / 0.66, 0, 1);
            const pulsePhase = clamp((progress - 0.26) / 0.5, 0, 1);

            const nodeStep = 0.72 / Math.max(scene.nodes.length, 1);
            const edgeStep = 0.72 / Math.max(scene.edges.length, 1);

            for (let i = 0; i < scene.edges.length; i += 1) {
                const edge = scene.edges[i];
                const from = scene.nodes[edge.from];
                const to = scene.nodes[edge.to];
                const threshold = 0.06 + i * edgeStep;
                const reveal = clamp((sequence - threshold) / 0.14, 0, 1);
                if (reveal <= 0) continue;

                const fromPoint = { x: from.x + from.size * 0.7, y: from.y };
                const toPoint = { x: to.x - to.size * 0.7, y: to.y };
                const [c1, c2] = smoothStepControls(fromPoint, toPoint);

                const steps = 26;
                context.beginPath();
                for (let s = 0; s <= steps; s += 1) {
                    const t = (s / steps) * reveal;
                    const p = bezierPoint(fromPoint, c1, c2, toPoint, t);
                    if (s === 0) {
                        context.moveTo(p.x, p.y);
                    } else {
                        context.lineTo(p.x, p.y);
                    }
                }
                context.strokeStyle = `hsla(${scene.hue}, 94%, 70%, ${0.22 * alpha})`;
                context.lineWidth = 1.25;
                context.stroke();

                if (pulsePhase > 0.05 && reveal > 0.98) {
                    const t = (pulsePhase + i * 0.18) % 1;
                    const p = bezierPoint(fromPoint, c1, c2, toPoint, t);
                    context.beginPath();
                    context.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
                    context.fillStyle = `hsla(${scene.hue + 10}, 98%, 76%, ${0.7 * alpha})`;
                    context.fill();
                }
            }

            for (let i = 0; i < scene.nodes.length; i += 1) {
                const node = scene.nodes[i];
                const threshold = i * nodeStep;
                const reveal = clamp((sequence - threshold) / 0.16, 0, 1);
                if (reveal <= 0) continue;

                const grow = 0.45 + reveal * 0.55;
                const cardWidth = node.size * 3.5 * grow;
                const cardHeight = node.size * 1.95 * grow;
                const x = node.x - cardWidth / 2;
                const y = node.y - cardHeight / 2;
                const radius = 7 * grow;

                const statusPalette: Record<WorkflowNode['status'], { stroke: RGB; glow: RGB; dot: RGB }> = {
                    pending: { stroke: [125, 138, 153], glow: [61, 74, 92], dot: [125, 138, 153] },
                    running: { stroke: [59, 130, 246], glow: [59, 130, 246], dot: [147, 197, 253] },
                    done: { stroke: [90, 159, 143], glow: [90, 159, 143], dot: [125, 211, 193] },
                    error: { stroke: [200, 84, 80], glow: [200, 84, 80], dot: [248, 113, 113] },
                };
                const palette = statusPalette[node.status];

                context.save();
                context.shadowBlur = 16;
                context.shadowColor = rgba(palette.glow, 0.32 * alpha * reveal);
                roundedRect(context, x, y, cardWidth, cardHeight, radius);
                context.fillStyle = `rgba(20, 28, 46, ${0.82 * alpha * reveal})`;
                context.fill();
                context.restore();

                roundedRect(context, x, y, cardWidth, cardHeight, radius);
                context.strokeStyle = rgba(palette.stroke, 0.78 * alpha * reveal);
                context.lineWidth = 1.2;
                context.stroke();

                context.fillStyle = `rgba(8,12,20,${0.62 * alpha * reveal})`;
                roundedRect(context, x + 1, y + 1, cardWidth - 2, cardHeight * 0.38, Math.max(3, radius - 2));
                context.fill();

                // Handles tipo pills
                const handleH = cardHeight * 0.34;
                const handleW = 4;
                context.fillStyle = `rgba(125, 138, 153, ${0.66 * alpha * reveal})`;
                roundedRect(context, x - handleW + 1, node.y - handleH / 2, handleW, handleH, 2.2);
                context.fill();
                roundedRect(context, x + cardWidth - 1, node.y - handleH / 2, handleW, handleH, 2.2);
                context.fill();

                // Dot de estado
                context.beginPath();
                context.arc(x + 9 * grow, y + 8 * grow, 1.8 * grow, 0, Math.PI * 2);
                context.fillStyle = rgba(palette.dot, 0.85 * alpha * reveal);
                context.fill();

                // Mini barra de progreso para running
                if (node.status === 'running') {
                    const barW = cardWidth * 0.5;
                    const barH = 2;
                    const bx = x + cardWidth * 0.28;
                    const by = y + cardHeight - 5;
                    context.fillStyle = `rgba(28,38,64,${0.7 * alpha * reveal})`;
                    context.fillRect(bx, by, barW, barH);
                    const pulse = ((now * 0.0012 + i * 0.33) % 1) * barW;
                    context.fillStyle = `rgba(59, 130, 246, ${0.88 * alpha * reveal})`;
                    context.fillRect(bx, by, pulse, barH);
                }
            }
        };

        const render = (now: number) => {
            if (document.hidden) {
                raf = window.requestAnimationFrame(render);
                return;
            }

            const width = canvas.clientWidth;
            const height = canvas.clientHeight;

            const stateBackdrop: Record<NonNullable<AuthGraphBackgroundProps['loginState']>, string> = {
                idle: 'rgba(8, 12, 20, 0.24)',
                verifying: 'rgba(8, 12, 20, 0.18)',
                success: 'rgba(8, 14, 12, 0.16)',
                error: 'rgba(20, 8, 8, 0.2)',
            };

            context.fillStyle = stateBackdrop[loginState];
            context.fillRect(0, 0, width, height);
            drawDotGrid(0.08);

            if (now - lastSpawn > 1500 && scenes.length < 4) {
                scenes.push(spawnWorkflowNext ? createWorkflowScene(now) : createOrganicScene(now));
                spawnWorkflowNext = !spawnWorkflowNext;
                lastSpawn = now;
            }

            for (let i = scenes.length - 1; i >= 0; i -= 1) {
                const scene = scenes[i];
                if (now - scene.start > scene.duration) {
                    scenes.splice(i, 1);
                    continue;
                }
                if (scene.mode === 'workflow') {
                    drawWorkflowScene(scene, now);
                } else {
                    drawOrganicScene(scene, now);
                }
            }

            raf = window.requestAnimationFrame(render);
        };

        const onMotionPreference = () => {
            resize();
            scenes.length = 0;
            context.fillStyle = '#080c14';
            context.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
            if (mediaQuery.matches) {
                window.cancelAnimationFrame(raf);
                drawStatic();
            } else {
                lastSpawn = 0;
                spawnWorkflowNext = true;
                window.cancelAnimationFrame(raf);
                raf = window.requestAnimationFrame(render);
            }
        };

        resize();
        context.fillStyle = '#080c14';
        context.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);
        onMotionPreference();

        window.addEventListener('resize', resize);
        mediaQuery.addEventListener('change', onMotionPreference);

        return () => {
            window.removeEventListener('resize', resize);
            mediaQuery.removeEventListener('change', onMotionPreference);
            window.cancelAnimationFrame(raf);
        };
    }, [loginState]);

    return (
        <canvas
            ref={canvasRef}
            className="absolute inset-0 h-full w-full pointer-events-none"
            aria-hidden="true"
        />
    );
}
