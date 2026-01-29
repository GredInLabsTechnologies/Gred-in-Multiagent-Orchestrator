import { useEffect, useRef, useState } from 'react';

/**
 * PS2-Style Ambient Float Engine (With Gentle Interactive Layer)
 * - Ultra-slow drift
 * - Wall bouncing with energy loss
 * - Simple elastic collisions
 * - Independent fade-in/fade-out lifecycles
 * - Subtle mouse repulsion for "fluid" feel
 */

interface Orb {
    id: number;
    x: number;
    y: number;
    vx: number;
    vy: number;
    radius: number;
    targetRadius: number; // The "full" visual size
    color: string;

    // Lifecycle
    fade: number;    // 0..1 current opacity multiplier
    fadeDir: 1 | -1; // Expanding (1) or Dying (-1)
    fadeSpeed: number;

    // Movement
    angle: number;           // For subtle organic drift
}

export const BackgroundLights = ({ active = true }: { active?: boolean }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const orbsRef = useRef<Orb[]>([]);
    const [orbs, setOrbs] = useState<Orb[]>([]); // STATE TO FORCE RENDER
    const lastRef = useRef(performance.now());
    const rafRef = useRef<number>();
    const mouseRef = useRef({ x: -9999, y: -9999 });

    // CONFIGURATION
    const ORB_COUNT = 15;
    const RESTITUTION = 0.92;
    const COLLISION_DAMPING = 0.98;
    const DRIFT = 0.002;
    const MOUSE_REPULSION = 300; // Interaction radius (Moderate)
    const MOUSE_FORCE = 0.02;    // Very gentle push (not a strike)

    const createOrb = (id: number, width: number, height: number): Orb => {
        const colors = [
            'bg-accent-primary',
            'bg-accent-secondary',
            'bg-purple-600',
            'bg-indigo-500',
            'bg-blue-500',
            'bg-cyan-500'
        ];

        return {
            id,
            x: Math.random() * width,
            y: Math.random() * height,
            vx: (Math.random() - 0.5) * 0.12,
            vy: (Math.random() - 0.5) * 0.12,

            radius: (150 + Math.random() * 200) * 0.35,
            targetRadius: 150 + Math.random() * 200,

            color: colors[Math.floor(Math.random() * colors.length)],

            fade: Math.random(),
            fadeDir: Math.random() > 0.5 ? 1 : -1,
            fadeSpeed: 0.003 + Math.random() * 0.005,

            angle: Math.random() * Math.PI * 2,
        };
    };

    useEffect(() => {
        const initialOrbs = Array.from({ length: ORB_COUNT }).map((_, i) =>
            createOrb(i, window.innerWidth, window.innerHeight)
        );
        orbsRef.current = initialOrbs;
        setOrbs(initialOrbs);

        const handleMouseMove = (e: MouseEvent) => {
            mouseRef.current = { x: e.clientX, y: e.clientY };
        };
        window.addEventListener('mousemove', handleMouseMove);

        const animate = () => {
            if (!containerRef.current) {
                rafRef.current = requestAnimationFrame(animate);
                return;
            }

            const now = performance.now();
            const dt = Math.min(0.033, (now - lastRef.current) / 1000);
            lastRef.current = now;

            const timeScale = dt * 60;

            const width = window.innerWidth;
            const height = window.innerHeight;

            const activeOrbs = orbsRef.current;

            activeOrbs.forEach(orb => {
                const el = containerRef.current?.children[orb.id] as HTMLElement;
                if (!el) return;

                // Lifecycle
                orb.fade = Math.max(0, Math.min(1, orb.fade + orb.fadeDir * orb.fadeSpeed * timeScale));

                if (orb.fade <= 0) {
                    if (Math.random() < 0.01) {
                        orb.fadeDir = 1;
                        orb.x = Math.random() * width;
                        orb.y = Math.random() * height;
                    }
                } else if (orb.fade >= 1) {
                    if (Math.random() < 0.005) orb.fadeDir = -1;
                }

                // Organic Drift
                orb.angle += (Math.random() - 0.5) * 0.05 * timeScale;
                orb.vx += Math.cos(orb.angle) * DRIFT * timeScale;
                orb.vy += Math.sin(orb.angle) * DRIFT * timeScale;

                // --- MOUSE INTERACTION (Soft) ---
                const dx = orb.x - mouseRef.current.x;
                const dy = orb.y - mouseRef.current.y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < MOUSE_REPULSION) {
                    const force = (1 - dist / MOUSE_REPULSION) * MOUSE_FORCE;
                    orb.vx += (dx / dist) * force * timeScale;
                    orb.vy += (dy / dist) * force * timeScale;

                    // Slight brighten on interact
                    if (orb.fade > 0.1) orb.fade = Math.min(1, orb.fade + 0.01 * timeScale);
                }

                // Apply Velocity
                orb.x += orb.vx * timeScale;
                orb.y += orb.vy * timeScale;

                // Wall Bounce
                const r = orb.targetRadius * 0.5;

                if (orb.x < r) { orb.x = r; orb.vx = Math.abs(orb.vx) * RESTITUTION; }
                if (orb.x > width - r) { orb.x = width - r; orb.vx = -Math.abs(orb.vx) * RESTITUTION; }

                if (orb.y < r) { orb.y = r; orb.vy = Math.abs(orb.vy) * RESTITUTION; }
                if (orb.y > height - r) { orb.y = height - r; orb.vy = -Math.abs(orb.vy) * RESTITUTION; }
            });

            // --- COLLISIONS ---
            for (let i = 0; i < activeOrbs.length; i++) {
                const a = activeOrbs[i];
                if (a.fade <= 0.05) continue;

                for (let j = i + 1; j < activeOrbs.length; j++) {
                    const b = activeOrbs[j];
                    if (b.fade <= 0.05) continue;

                    const dx = b.x - a.x;
                    const dy = b.y - a.y;
                    const dist2 = dx * dx + dy * dy;

                    const minDist = a.radius + b.radius;

                    if (dist2 < minDist * minDist && dist2 > 0.0001) {
                        const dist = Math.sqrt(dist2);
                        const nx = dx / dist;
                        const ny = dy / dist;

                        const overlap = (minDist - dist) * 0.5;
                        a.x -= nx * overlap; a.y -= ny * overlap;
                        b.x += nx * overlap; b.y += ny * overlap;

                        const dvx = b.vx - a.vx;
                        const dvy = b.vy - a.vy;
                        const impulse = (dvx * nx + dvy * ny);

                        if (impulse < 0) {
                            const ix = impulse * nx;
                            const iy = impulse * ny;
                            a.vx += ix; a.vy += iy;
                            b.vx -= ix; b.vy -= iy;

                            a.vx *= COLLISION_DAMPING; a.vy *= COLLISION_DAMPING;
                            b.vx *= COLLISION_DAMPING; b.vy *= COLLISION_DAMPING;
                        }
                    }
                }
            }

            // --- RENDER ---
            activeOrbs.forEach(orb => {
                const el = containerRef.current?.children[orb.id] as HTMLElement;
                if (!el) return;

                el.style.opacity = (orb.fade * 0.4).toFixed(3);

                const size = orb.targetRadius;
                el.style.transform = `translate3d(${orb.x - size / 2}px, ${orb.y - size / 2}px, 0)`;
                el.style.width = `${size}px`;
                el.style.height = `${size}px`;
            });

            rafRef.current = requestAnimationFrame(animate);
        };

        rafRef.current = requestAnimationFrame(animate);

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
        };
    }, []);

    if (!active) return null;

    return (
        <div ref={containerRef} className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
            {orbs.map((orb) => (
                <div
                    key={orb.id}
                    className={`absolute rounded-full mix-blend-screen will-change-transform blur-[70px] ${orb.color}`}
                    style={{
                        opacity: 0,
                    }}
                />
            ))}
        </div>
    );
};
