import React, { useEffect, useRef } from 'react';

interface Spark {
  x: number;
  y: number;
  vx: number;
  vy: number;
  col: { r: number; g: number; b: number };
}

const PALETTE = [
  { r: 251, g: 146, b: 60 },
  { r: 249, g: 115, b: 22 },
  { r: 251, g: 191, b: 36 },
  { r: 255, g: 237, b: 213 },
  { r: 234, g: 88, b: 12 },
];

const InteractiveBackground: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    let sparks: Spark[] = [];
    const mouse = { x: -9999, y: -9999 };

    const scatter = (w: number, h: number) => {
      const count = Math.max(120, Math.min(320, Math.floor(w / 5)));
      sparks = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
        col: PALETTE[Math.floor(Math.random() * PALETTE.length)],
      }));
    };

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = canvas.offsetWidth * dpr;
      canvas.height = canvas.offsetHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      scatter(canvas.offsetWidth, canvas.offsetHeight);
    };

    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    };

    const onMouseLeave = () => {
      mouse.x = -9999;
      mouse.y = -9999;
    };

    const flowAngle = (x: number, y: number, t: number) => {
      const n =
        Math.sin(x * 0.0016 + t * 0.00055) * 0.5 +
        Math.sin(y * 0.0014 - t * 0.0005) * 0.3 +
        Math.sin((x + y) * 0.0008 + t * 0.00045) * 0.2;
      return n * Math.PI * 3.2;
    };

    let glowCache: CanvasGradient | null = null;
    let glowCenter = '';

    const createGlow = (x: number, y: number, r: number) => {
      const key = `${Math.round(x)},${Math.round(y)}`;
      if (!glowCache || glowCenter !== key) {
        glowCache = ctx.createRadialGradient(x, y, 0, x, y, r);
        glowCache.addColorStop(0, 'rgba(249, 115, 22, 0.22)');
        glowCache.addColorStop(1, 'rgba(249, 115, 22, 0)');
        glowCenter = key;
      }
      return glowCache;
    };

    const step = (t: number) => {
      const w = canvas.offsetWidth;
      const h = canvas.offsetHeight;

      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = 'rgba(255, 248, 242, 0.10)';
      ctx.fillRect(0, 0, w, h);

      ctx.globalCompositeOperation = 'lighter';

      for (const p of sparks) {
        const a = flowAngle(p.x, p.y, t);
        p.vx += Math.cos(a) * 0.03;
        p.vy += Math.sin(a) * 0.03;

        const dx = p.x - mouse.x;
        const dy = p.y - mouse.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 260 && dist > 0.1) {
          const f = (260 - dist) / 260;
          const ang = Math.atan2(dy, dx) + Math.PI / 2;
          p.vx += Math.cos(ang) * f * 0.16;
          p.vy += Math.sin(ang) * f * 0.16;
          p.vx -= (dx / dist) * f * 0.04;
          p.vy -= (dy / dist) * f * 0.04;
        }

        p.vx *= 0.985;
        p.vy *= 0.985;
        const sp = Math.hypot(p.vx, p.vy);
        const max = 1.6;
        if (sp > max) {
          p.vx = (p.vx / sp) * max;
          p.vy = (p.vy / sp) * max;
        }

        p.x += p.vx;
        p.y += p.vy;

        if (p.x < -20) p.x = w + 20;
        if (p.x > w + 20) p.x = -20;
        if (p.y < -20) p.y = h + 20;
        if (p.y > h + 20) p.y = -20;

        const speed = Math.min(1, sp / 1.3);
        const alpha = 0.28 + speed * 0.65;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.2 + speed * 2.2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${p.col.r}, ${p.col.g}, ${p.col.b}, ${alpha})`;
        ctx.fill();
      }

      const glow = createGlow(mouse.x, mouse.y, 190);
      ctx.fillStyle = glow;
      ctx.fillRect(mouse.x - 190, mouse.y - 190, 380, 380);

      raf = requestAnimationFrame(step);
    };

    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', onMouseMove);
    document.documentElement.addEventListener('mouseleave', onMouseLeave);
    raf = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', onMouseMove);
      document.documentElement.removeEventListener('mouseleave', onMouseLeave);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="absolute inset-0 w-full h-full pointer-events-none"
    />
  );
};

export default InteractiveBackground;
