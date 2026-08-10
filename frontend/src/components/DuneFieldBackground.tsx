import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

const DuneFieldBackground: React.FC = () => {
  const holderRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const holder = holderRef.current;
    const canvas = canvasRef.current;
    if (!holder || !canvas) return;

    let renderer: THREE.WebGLRenderer | null = null;
    let scene: THREE.Scene | null = null;
    let camera: THREE.PerspectiveCamera | null = null;
    let dotsMesh: THREE.Points | null = null;
    let frameId: number | null = null;

    const lookTarget = new THREE.Vector3(0, -0.4, 0);

    const uniforms = {
      uTime: { value: 0 },
      uSpeed: { value: 0.16 },
      uElevation: { value: 0.22 },
      uNoiseRange: { value: 0.95 },
      uPointSize: { value: 44 },
      uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 1.75) },
      uMouse: { value: new THREE.Vector2(9999, 9999) },
      uRadius: { value: 3.6 },
      uLineColor: { value: new THREE.Color('#F76A25') },
      uGlowColor: { value: new THREE.Color('#2b0a00') },
      uAccentColor: { value: new THREE.Color('#ff9e43') },
    };

    const vertexShader = `
      uniform float uTime;
      uniform float uSpeed;
      uniform float uElevation;
      uniform float uNoiseRange;
      uniform float uPointSize;
      uniform float uPixelRatio;
      uniform vec2 uMouse;
      uniform float uRadius;

      varying vec2 vUv;
      varying float vHeight;
      varying float vHeat;

      vec3 mod289(vec3 x) {
        return x - floor(x * (1.0 / 289.0)) * 289.0;
      }

      vec4 mod289(vec4 x) {
        return x - floor(x * (1.0 / 289.0)) * 289.0;
      }

      vec4 permute(vec4 x) {
        return mod289(((x * 34.0) + 1.0) * x);
      }

      vec4 taylorInvSqrt(vec4 r) {
        return 1.79284291400159 - 0.85373472095314 * r;
      }

      float cnoise(vec3 P) {
        vec3 Pi0 = floor(P);
        vec3 Pi1 = Pi0 + vec3(1.0);
        Pi0 = mod289(Pi0);
        Pi1 = mod289(Pi1);
        vec3 Pf0 = fract(P);
        vec3 Pf1 = Pf0 - vec3(1.0);
        vec4 ix = vec4(Pi0.x, Pi1.x, Pi0.x, Pi1.x);
        vec4 iy = vec4(Pi0.yy, Pi1.yy);
        vec4 iz0 = Pi0.zzzz;
        vec4 iz1 = Pi1.zzzz;

        vec4 ixy = permute(permute(ix) + iy);
        vec4 ixy0 = permute(ixy + iz0);
        vec4 ixy1 = permute(ixy + iz1);

        vec4 gx0 = ixy0 * (1.0 / 7.0);
        vec4 gy0 = fract(floor(gx0) * (1.0 / 7.0)) - 0.5;
        gx0 = fract(gx0);
        vec4 gz0 = vec4(0.5) - abs(gx0) - abs(gy0);
        vec4 sz0 = step(gz0, vec4(0.0));
        gx0 -= sz0 * (step(0.0, gx0) - 0.5);
        gy0 -= sz0 * (step(0.0, gy0) - 0.5);

        vec4 gx1 = ixy1 * (1.0 / 7.0);
        vec4 gy1 = fract(floor(gx1) * (1.0 / 7.0)) - 0.5;
        gx1 = fract(gx1);
        vec4 gz1 = vec4(0.5) - abs(gx1) - abs(gy1);
        vec4 sz1 = step(gz1, vec4(0.0));
        gx1 -= sz1 * (step(0.0, gx1) - 0.5);
        gy1 -= sz1 * (step(0.0, gy1) - 0.5);

        vec3 g000 = vec3(gx0.x, gy0.x, gz0.x);
        vec3 g100 = vec3(gx0.y, gy0.y, gz0.y);
        vec3 g010 = vec3(gx0.z, gy0.z, gz0.z);
        vec3 g110 = vec3(gx0.w, gy0.w, gz0.w);
        vec3 g001 = vec3(gx1.x, gy1.x, gz1.x);
        vec3 g101 = vec3(gx1.y, gy1.y, gz1.y);
        vec3 g011 = vec3(gx1.z, gy1.z, gz1.z);
        vec3 g111 = vec3(gx1.w, gy1.w, gz1.w);

        vec4 norm0 = taylorInvSqrt(vec4(dot(g000, g000), dot(g010, g010), dot(g100, g100), dot(g110, g110)));
        g000 *= norm0.x;
        g010 *= norm0.y;
        g100 *= norm0.z;
        g110 *= norm0.w;
        vec4 norm1 = taylorInvSqrt(vec4(dot(g001, g001), dot(g011, g011), dot(g101, g101), dot(g111, g111)));
        g001 *= norm1.x;
        g011 *= norm1.y;
        g101 *= norm1.z;
        g111 *= norm1.w;

        float n000 = dot(g000, Pf0);
        float n100 = dot(g100, vec3(Pf1.x, Pf0.y, Pf0.z));
        float n010 = dot(g010, vec3(Pf0.x, Pf1.y, Pf0.z));
        float n110 = dot(g110, vec3(Pf1.xy, Pf0.z));
        float n001 = dot(g001, vec3(Pf0.xy, Pf1.z));
        float n101 = dot(g101, vec3(Pf1.x, Pf0.y, Pf1.z));
        float n011 = dot(g011, vec3(Pf0.x, Pf1.yz));
        float n111 = dot(g111, Pf1);

        vec3 fade_xyz = Pf0 * Pf0 * Pf0 * (Pf0 * (Pf0 * 6.0 - 15.0) + 10.0);
        vec4 n_z = mix(vec4(n000, n100, n010, n110), vec4(n001, n101, n011, n111), fade_xyz.z);
        vec2 n_yz = mix(n_z.xy, n_z.zw, fade_xyz.y);
        return mix(n_yz.x, n_yz.y, fade_xyz.x);
      }

      void main() {
        vUv = uv;
        float t = uTime * uSpeed;
        float gentleT = t * 0.6;
        vec2 p = position.xz;

        float primary = cnoise(vec3(p * 0.22, gentleT)) * uNoiseRange;
        float ribbon = sin(position.x * 0.32 - 1.57079632679) * uElevation;

        vec2 centeredUv = uv - 0.5;
        float radius = length(centeredUv);
        float radialAttenuation = mix(0.65, 1.0, smoothstep(0.0, 0.28, radius));

        vec2 toMouse = position.xy - uMouse;
        float md = length(toMouse);
        float influence = 1.0 - smoothstep(0.0, uRadius, md);
        vHeat = influence;

        float height = (primary + ribbon) * radialAttenuation;
        vHeight = height;

        vec3 displacedPosition = vec3(position.x, position.y, height);
        vec4 mvPosition = modelViewMatrix * vec4(displacedPosition, 1.0);
        gl_PointSize = (uPointSize * uPixelRatio * (1.0 + influence * 0.9)) / max(1.0, -mvPosition.z);
        gl_Position = projectionMatrix * mvPosition;
      }
    `;

    const fragmentShader = `
      uniform vec3 uLineColor;
      uniform vec3 uAccentColor;

      varying vec2 vUv;
      varying float vHeat;

      void main() {
        vec2 c = gl_PointCoord - 0.5;
        float d = length(c) * 2.0;
        float falloff = smoothstep(1.0, 0.0, d);
        falloff = pow(falloff, 1.5);

        float edgeDist = min(min(vUv.x, 1.0 - vUv.x), min(vUv.y, 1.0 - vUv.y));
        float edgeFade = smoothstep(0.0, 0.3, edgeDist);
        edgeFade = edgeFade * edgeFade * (3.0 - 2.0 * edgeFade);

        vec3 col = mix(uLineColor, uAccentColor, 0.35 + vHeat * 0.5);
        float alpha = falloff * (0.4 + 0.6 * vHeat) * edgeFade * 0.95;
        gl_FragColor = vec4(col, alpha);
      }
    `;

    scene = new THREE.Scene();

    const width = holder.clientWidth || window.innerWidth;
    const height = holder.clientHeight || window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.75);

    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(dpr);
    renderer.setSize(width, height, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);

    camera = new THREE.PerspectiveCamera(52, width / height, 0.1, 80);
    camera.position.set(0, 3.1, 9.8);
    camera.lookAt(lookTarget);

    const geometry = new THREE.PlaneGeometry(72, 52, 150, 90);
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader,
      fragmentShader,
      transparent: true,
      depthTest: true,
      depthWrite: false,
      blending: THREE.NormalBlending,
    });

    dotsMesh = new THREE.Points(geometry, material);
    dotsMesh.rotation.x = -Math.PI / 2;
    dotsMesh.position.y = -0.3;
    scene.add(dotsMesh);

    const handleResize = () => {
      if (!renderer || !camera || !holder) return;
      const w = holder.clientWidth || window.innerWidth;
      const h = holder.clientHeight || window.innerHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.75);
      uniforms.uPixelRatio.value = ratio;
      renderer.setPixelRatio(ratio);
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };

    const clock = new THREE.Clock();

    const raycaster = new THREE.Raycaster();
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0.3);

    const onMouseMove = (e: MouseEvent) => {
      if (!camera) return;
      const rect = canvas.getBoundingClientRect();
      const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ny = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      camera.updateMatrixWorld(true);
      raycaster.setFromCamera(new THREE.Vector2(nx, ny), camera);
      const hit = new THREE.Vector3();
      if (raycaster.ray.intersectPlane(groundPlane, hit)) {
        uniforms.uMouse.value.set(hit.x, -hit.z);
      }
    };

    const onMouseLeave = () => {
      uniforms.uMouse.value.set(9999, 9999);
    };

    const renderFrame = () => {
      const elapsed = clock.getElapsedTime();
      uniforms.uTime.value = elapsed;

      if (dotsMesh) {
        dotsMesh.rotation.z = Math.sin(elapsed * 0.08) * 0.06;
      }

      if (camera) {
        const orbit = Math.sin(elapsed * 0.028) * 0.24;
        camera.position.x = orbit;
        camera.lookAt(lookTarget);
      }

      if (renderer && scene && camera) {
        renderer.render(scene, camera);
        frameId = requestAnimationFrame(renderFrame);
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize, { passive: true });
    window.addEventListener('mousemove', onMouseMove, { passive: true });
    document.documentElement.addEventListener('mouseleave', onMouseLeave);
    frameId = requestAnimationFrame(renderFrame);

    return () => {
      if (frameId !== null) cancelAnimationFrame(frameId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', onMouseMove);
      document.documentElement.removeEventListener('mouseleave', onMouseLeave);

      if (dotsMesh) {
        dotsMesh.geometry.dispose();
        (dotsMesh.material as THREE.Material).dispose();
      }
      if (renderer) {
        renderer.dispose();
      }
      dotsMesh = null;
      renderer = null;
      scene = null;
      camera = null;
    };
  }, []);

  return (
    <div ref={holderRef} className="absolute inset-0 pointer-events-none">
      <canvas ref={canvasRef} className="block w-full h-full" />
    </div>
  );
};

export default DuneFieldBackground;
