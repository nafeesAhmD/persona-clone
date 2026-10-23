"use client";

import { useEffect, useRef } from "react";
import type * as THREE from "three";

export function RobotMascot({ className }: { className?: string }) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let disposed = false;
    let teardown: (() => void) | undefined;

    import("three").then((three) => {
      if (disposed) return;
      teardown = buildRobot(three, host);
    });

    return () => {
      disposed = true;
      teardown?.();
    };
  }, []);

  return <div ref={hostRef} className={className} aria-hidden />;
}

function buildRobot(three: typeof import("three"), host: HTMLDivElement): () => void {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const styles = getComputedStyle(document.documentElement);
  const readColor = (name: string, fallback: string) =>
    new three.Color(styles.getPropertyValue(name).trim() || fallback);

  const accent = readColor("--color-accent", "#ff6b35");
  const cyan = readColor("--color-cyan", "#38d9f5");

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new three.WebGLRenderer({ alpha: true, antialias: true });
  } catch {
    return () => {};
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = three.SRGBColorSpace;
  renderer.toneMapping = three.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  renderer.setClearAlpha(0);

  const canvas = renderer.domElement;
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  canvas.style.pointerEvents = "none";
  host.appendChild(canvas);

  const scene = new three.Scene();
  const camera = new three.PerspectiveCamera(34, 1, 0.1, 100);
  camera.position.set(0, -0.45, 10.5);

  const envScene = new three.Scene();
  envScene.add(
    new three.Mesh(
      new three.BoxGeometry(40, 40, 40),
      new three.MeshBasicMaterial({ color: 0x1a1c3a, side: three.BackSide }),
    ),
  );
  const envPanels: [THREE.ColorRepresentation, number, number, number][] = [
    [cyan, -12, 4, 6],
    [accent, 12, 2, 6],
    [0xffffff, 0, 14, 6],
    [0xffffff, 4, 3, 14],
    [0x88aaff, -8, -4, -10],
  ];
  for (const [color, x, y, z] of envPanels) {
    const panel = new three.Mesh(
      new three.PlaneGeometry(14, 8),
      new three.MeshBasicMaterial({ color, side: three.DoubleSide }),
    );
    panel.position.set(x, y, z);
    panel.lookAt(0, 0, 0);
    envScene.add(panel);
  }
  const pmrem = new three.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(envScene, 0.03).texture;
  pmrem.dispose();

  const keyLight = new three.DirectionalLight(0xffffff, 1);
  keyLight.position.set(2, 4, 7);
  scene.add(keyLight);
  const accentLight = new three.PointLight(accent, 2, 16);
  accentLight.position.set(-4, 1, 3);
  scene.add(accentLight);
  const cyanLight = new three.PointLight(cyan, 2, 16);
  cyanLight.position.set(4, -1, 3);
  scene.add(cyanLight);

  const physical = (
    color: THREE.ColorRepresentation,
    metalness: number,
    roughness: number,
    clearcoat = 0,
  ) =>
    new three.MeshPhysicalMaterial({
      color,
      metalness,
      roughness,
      clearcoat,
      clearcoatRoughness: 0.12,
    });

  const ceramic = physical(0xe9ecf5, 0.1, 0.25, 1);
  const glass = physical(0x060912, 0.4, 0.05, 1);
  const accentMat = physical(accent, 0.8, 0.25, 0.6);
  const gunmetal = physical(0x2b3042, 0.8, 0.35, 0.3);
  const glowMat = new three.MeshBasicMaterial({ color: accent.clone(), toneMapped: false });

  const mesh = (geometry: THREE.BufferGeometry, material: THREE.Material, x = 0, y = 0, z = 0) => {
    const object = new three.Mesh(geometry, material);
    object.position.set(x, y, z);
    return object;
  };
  const clamp = (value: number, limit: number) => Math.max(-limit, Math.min(limit, value));

  const bot = new three.Group();
  scene.add(bot);
  const robo = new three.Group();
  bot.add(robo);

  const HEAD_Y = 0.9;
  const head = new three.Group();
  head.position.y = HEAD_Y;
  robo.add(head);

  const shell = mesh(new three.SphereGeometry(1, 96, 96), ceramic);
  shell.scale.set(1.02, 1.1, 1);
  head.add(shell);

  const faceplate = mesh(new three.SphereGeometry(1, 64, 48), glass, 0, -0.05, 0.4);
  faceplate.scale.set(0.84, 0.66, 0.72);
  head.add(faceplate);

  const body = mesh(new three.SphereGeometry(1, 64, 48), ceramic, 0, -1.0, 0);
  body.scale.set(0.82, 0.95, 0.74);
  robo.add(body);

  robo.updateMatrixWorld(true);
  bot.updateMatrixWorld(true);

  const raycaster = new three.Raycaster();
  const place = (
    object: THREE.Object3D,
    x: number,
    y: number,
    offset: number,
    target: THREE.Object3D,
    targetY: number,
  ) => {
    raycaster.set(new three.Vector3(x, y + targetY, 6), new three.Vector3(0, 0, -1));
    const hit = raycaster.intersectObject(target, false)[0];
    object.position.set(x, y, (hit ? hit.point.z : 0.9) + offset);
    return object;
  };

  const glowCanvas = document.createElement("canvas");
  glowCanvas.width = glowCanvas.height = 64;
  const glowCtx = glowCanvas.getContext("2d");
  if (glowCtx) {
    const gradient = glowCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, "rgba(255,255,255,1)");
    gradient.addColorStop(0.3, "rgba(255,255,255,.35)");
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    glowCtx.fillStyle = gradient;
    glowCtx.fillRect(0, 0, 64, 64);
  }
  const glowTexture = new three.CanvasTexture(glowCanvas);

  const glowSprites: THREE.Sprite[] = [];
  const sprite = (size: number, opacity: number, color: THREE.ColorRepresentation) => {
    const evenGlow = new three.Sprite(
      new three.SpriteMaterial({
        map: glowTexture,
        color,
        blending: three.AdditiveBlending,
        transparent: true,
        depthWrite: false,
        opacity,
      }),
    );
    evenGlow.scale.set(size, size, 1);
    return evenGlow;
  };

  const eyeMaterial = new three.MeshBasicMaterial({ color: accent.clone(), toneMapped: false });
  const eyes: { root: THREE.Group; eye: THREE.Mesh; bx: number; by: number }[] = [];
  for (const side of [-1, 1]) {
    const root = new three.Group();
    head.add(root);
    place(root, side * 0.34, 0.1, 0, faceplate, HEAD_Y);
    const eye = mesh(new three.SphereGeometry(0.17, 32, 16), eyeMaterial);
    eye.scale.set(0.72, 1.1, 0.25);
    root.add(eye);
    root.add(
      mesh(
        new three.SphereGeometry(0.035, 12, 12),
        new three.MeshBasicMaterial({ color: 0xffffff, toneMapped: false }),
        0.05,
        0.09,
        0.03,
      ),
    );
    const eyeGlow = sprite(0.8, 0.8, accent);
    eyeGlow.position.z = 0.03;
    root.add(eyeGlow);
    glowSprites.push(eyeGlow);
    eyes.push({ root, eye, bx: side * 0.34, by: 0.1 });
  }

  const bars: THREE.Mesh[] = [];
  for (let i = 0; i < 7; i += 1) {
    const x = (i - 3) * 0.075;
    const bar = mesh(new three.BoxGeometry(0.045, 0.05, 0.03), glowMat);
    place(bar, x, -0.4 + x * x * 2.4, 0.01, faceplate, HEAD_Y);
    bar.userData.x = x;
    head.add(bar);
    bars.push(bar);
  }

  const cheeks = [-1, 1].map((side) => {
    const cheek = sprite(0.6, 0.1, cyan);
    place(cheek, side * 0.55, -0.2, 0.02, faceplate, HEAD_Y);
    head.add(cheek);
    return cheek;
  });

  for (const side of [-1, 1]) {
    const ear = mesh(new three.CylinderGeometry(0.27, 0.27, 0.2, 40), accentMat, side * 1.06, -0.05, 0);
    ear.rotation.z = Math.PI / 2;
    head.add(ear);
    const earRing = mesh(new three.TorusGeometry(0.17, 0.025, 10, 40), glowMat, side * 1.17, -0.05, 0);
    earRing.rotation.y = Math.PI / 2;
    head.add(earRing);
  }

  const antenna = new three.Group();
  antenna.position.set(0, 1.0, -0.05);
  head.add(antenna);
  antenna.add(mesh(new three.CylinderGeometry(0.03, 0.04, 0.5, 12), gunmetal, 0, 0.25, 0));
  const antennaTip = mesh(
    new three.SphereGeometry(0.1, 20, 20),
    new three.MeshBasicMaterial({ color: cyan.clone(), toneMapped: false }),
    0,
    0.55,
    0,
  );
  antenna.add(antennaTip);
  const tipGlow = sprite(0.7, 0.7, cyan);
  tipGlow.position.y = 0.55;
  antenna.add(tipGlow);
  glowSprites.push(tipGlow);

  const crown = mesh(new three.TorusGeometry(0.9, 0.03, 10, 64), accentMat, 0, 0.62, 0);
  crown.rotation.x = Math.PI / 2;
  head.add(crown);

  const neck = mesh(new three.TorusGeometry(0.38, 0.06, 12, 32), gunmetal, 0, -0.08, 0);
  neck.rotation.x = Math.PI / 2;
  robo.add(neck);
  const bodyBand = mesh(new three.TorusGeometry(0.81, 0.03, 10, 64), accentMat, 0, -1.15, 0);
  bodyBand.scale.y = 0.9;
  bodyBand.rotation.x = Math.PI / 2;
  robo.add(bodyBand);

  const core = place(mesh(new three.SphereGeometry(0.14, 24, 24), glowMat), 0, -0.75, 0.02, body, 0);
  robo.add(core);
  robo.add(place(mesh(new three.TorusGeometry(0.22, 0.03, 12, 32), accentMat), 0, -0.75, 0, body, 0));
  const coreGlow = sprite(1, 0.5, accent);
  coreGlow.position.set(0, -0.75, core.position.z + 0.05);
  robo.add(coreGlow);
  glowSprites.push(coreGlow);

  const arms: THREE.Group[] = [];
  for (const side of [-1, 1]) {
    const shoulder = new three.Group();
    shoulder.position.set(side * 0.8, -0.7, 0);
    robo.add(shoulder);
    shoulder.add(mesh(new three.SphereGeometry(0.17, 24, 24), accentMat));
    shoulder.add(mesh(new three.CylinderGeometry(0.12, 0.1, 0.6, 20), ceramic, 0, -0.36, 0));
    shoulder.add(mesh(new three.SphereGeometry(0.15, 20, 20), gunmetal, 0, -0.72, 0));
    arms.push(shoulder);
  }

  robo.add(mesh(new three.CylinderGeometry(0.34, 0.2, 0.25, 28), gunmetal, 0, -2.02, 0));
  const flame = mesh(
    new three.ConeGeometry(0.22, 0.8, 20, 1, true),
    new three.MeshBasicMaterial({
      color: cyan.clone(),
      transparent: true,
      opacity: 0.55,
      blending: three.AdditiveBlending,
      depthWrite: false,
      side: three.DoubleSide,
      toneMapped: false,
    }),
    0,
    -2.5,
    0,
  );
  flame.rotation.x = Math.PI;
  robo.add(flame);
  const flameGlow = sprite(1.6, 0.7, cyan);
  flameGlow.position.y = -2.2;
  robo.add(flameGlow);
  glowSprites.push(flameGlow);

  const layout = () => {
    const width = host.clientWidth || 1;
    const height = host.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const fit = Math.min(width, height);
    bot.scale.setScalar(Math.max(0.45, Math.min(1, fit / 300)));
  };
  layout();
  const resizeObserver = new ResizeObserver(layout);
  resizeObserver.observe(host);

  const pointer = { x: 0, y: 0 };
  const onPointerMove = (event: PointerEvent) => {
    const rect = host.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    pointer.x = clamp(((event.clientX - (rect.left + rect.width / 2)) / (rect.width / 2)) * 1.5, 1);
    pointer.y = clamp(((event.clientY - (rect.top + rect.height / 2)) / (rect.height / 2)) * 1.5, 1);
  };
  window.addEventListener("pointermove", onPointerMove, { passive: true });

  let headYaw = 0;
  let headPitch = 0;
  let eyeShift = 0;
  let mouthOpen = 0;
  let blinkAt = -1;
  let nextBlink = 2;
  let frame = 0;
  const startTime = performance.now();

  const render = (now: number) => {
    const time = (now - startTime) / 1000;
    const idle = reduceMotion ? 0 : 1;

    headYaw += (pointer.x - headYaw) * 0.12;
    headPitch += (pointer.y - headPitch) * 0.12;
    eyeShift += (pointer.x - eyeShift) * 0.1;

    robo.position.y = Math.sin(time * 1.8) * 0.11 * idle;
    robo.rotation.z = -pointer.x * 0.05 * idle + Math.sin(time * 0.8) * 0.02 * idle;

    head.rotation.y = clamp(headYaw * 0.7, 0.8);
    head.rotation.x = clamp(headPitch * 0.26, 0.32) - 0.03;
    head.rotation.z = -headYaw * 0.04 + Math.sin(time * 0.8) * 0.02 * idle;

    if (!reduceMotion && time > nextBlink && blinkAt < 0) {
      blinkAt = time;
      nextBlink = time + 2 + Math.random() * 3.5;
    }
    let blink = 0;
    if (blinkAt >= 0) {
      const phase = (time - blinkAt) / 0.18;
      blink = phase < 1 ? Math.sin(phase * Math.PI) : 0;
      if (phase >= 1) blinkAt = -1;
    }

    for (const eye of eyes) {
      eye.root.position.x = eye.bx + eyeShift * 0.06;
      eye.root.position.y = eye.by - pointer.y * 0.04;
      eye.eye.scale.y = 1.1 * (1 - blink * 0.9);
    }

    mouthOpen += ((reduceMotion ? 0 : 0.35 + Math.abs(Math.sin(time * 3))) - mouthOpen) * 0.2;
    bars.forEach((bar, index) => {
      const x = (bar.userData.x as number) ?? 0;
      bar.position.y = -0.4 + x * x * 2.4;
      bar.scale.y = 0.7 + mouthOpen * 0.4 * Math.abs(Math.sin(time * 8 + index));
    });

    cheeks.forEach((cheek) => {
      cheek.material.opacity = 0.1 + idle * 0.2;
    });

    antenna.rotation.z = Math.sin(time * 2.2) * 0.15 * idle - pointer.x * 0.2;
    antenna.rotation.x = Math.sin(time * 1.7) * 0.08 * idle - pointer.y * 0.1;
    antennaTip.scale.setScalar(1 + Math.abs(Math.sin(time * 3)) * 0.3 * idle);

    arms[0].rotation.z = 0.35 + Math.sin(time * 1.6) * 0.06 * idle;
    arms[1].rotation.z = -0.35 - Math.sin(time * 1.6 + 1) * 0.06 * idle;

    const flamePulse = idle;
    flame.scale.set(
      1 + Math.sin(time * 30) * 0.08 * flamePulse,
      1 + Math.sin(time * 23) * 0.15 * flamePulse,
      1 + Math.sin(time * 30) * 0.08 * flamePulse,
    );

    accentLight.position.x = -4 + pointer.x * 3;
    cyanLight.position.x = 4 + pointer.x * 3;

    renderer.render(scene, camera);
    frame = requestAnimationFrame(render);
  };
  frame = requestAnimationFrame(render);

  return () => {
    cancelAnimationFrame(frame);
    window.removeEventListener("pointermove", onPointerMove);
    resizeObserver.disconnect();
    for (const sceneRoot of [scene, envScene]) {
      sceneRoot.traverse((object) => {
        const withGeometry = object as THREE.Mesh;
        withGeometry.geometry?.dispose();
        const material = withGeometry.material;
        if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
        else material?.dispose();
      });
    }
    glowTexture.dispose();
    renderer.dispose();
    canvas.remove();
  };
}
