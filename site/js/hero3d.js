// Hero scene: speech flows in as a particle waveform, hits the app icon (built in 3D from
// the exact geometry of assets/make_icon.py), and leaves as timed SRT cues.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const hero = document.querySelector('.hero');
const canvas = document.querySelector('[data-hero-canvas]');
const coarsePointer = matchMedia('(pointer: coarse)').matches;
const qs = new URLSearchParams(location.search);
// ?still=<seconds> renders one deterministic frame of the timeline (QA, social-card capture).
const stillAt = Number.parseFloat(qs.get('still'));
const isStill = Number.isFinite(stillAt) && stillAt >= 0;
// ?debug logs cue slot/birth/age/text to the console once a second (QA only, no visual output).
const isDebug = qs.has('debug');
// A still capture is a QA/social-card tool, not a real visitor session: simulate full motion by
// default so the capture shows the real timeline, unless ?reduced is also passed to deliberately
// preview the reduced-motion fallback. The live page always honours the real OS/browser setting.
const reduceMotion = isStill ? qs.has('reduced') : matchMedia('(prefers-reduced-motion: reduce)').matches;

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smooth = (a, b, v) => { const t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const easeOut = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);
const damp = (from, to, lambda, dt) => THREE.MathUtils.lerp(from, to, 1 - Math.exp(-lambda * dt));
const srgb = (hex) => { const n = parseInt(hex.slice(1), 16); return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255); };

function webgl2() {
  try { return !!document.createElement('canvas').getContext('webgl2'); } catch { return false; }
}
// Data Saver on: skip the WebGL scene and three.js download, keep the CSS/logo poster fallback.
// still= is a QA/social-card capture, not a real constrained-data visitor, so it bypasses this.
const saveData = !!navigator.connection?.saveData;

if (hero && canvas && webgl2() && (!saveData || new URLSearchParams(location.search).has('still'))) {
  start().catch((err) => {
    console.warn('[hero3d] falling back to the static poster:', err);
    hero.classList.remove('is-3d');
  });
}

async function start() {
  /* ---------- Renderer / scene ---------- */
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  let dprCap = coarsePointer ? 1.5 : 2;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, dprCap));

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.38;

  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 80);
  const rig = new THREE.Group();
  scene.add(rig);

  scene.add(new THREE.AmbientLight(0x9ffff4, 0.12));
  const key = new THREE.DirectionalLight(0xffffff, 1.7);
  key.position.set(-4, 5, 7);
  scene.add(key);
  const rim = new THREE.PointLight(0x4ae2d2, 60, 14, 2);
  rim.position.set(2.8, 1.8, -2.6);
  scene.add(rim);
  const fill = new THREE.PointLight(0x2aa3a8, 18, 10, 2);
  fill.position.set(-2.2, -2.4, 2.8);
  scene.add(fill);

  /* ---------- The app icon, in 3D ---------- */
  const S = 1.7; // tile edge in world units (the icon is drawn on a 256px square)
  const TILE_Y = -0.62;
  const icon = new THREE.Group();
  icon.position.set(0, TILE_Y, 0);
  rig.add(icon);

  const px = (x) => (x / 256 - 0.5) * S;
  const py = (y) => (0.5 - y / 256) * S;

  const bevel = 0.06;
  const depth = 0.22;
  const shape = roundedSquare(S - bevel * 2, S / 8 - bevel);
  const tileGeo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 10, curveSegments: 36 });
  tileGeo.center();
  const front = depth / 2 + bevel;
  const tileMat = new THREE.MeshPhysicalMaterial({
    color: 0x207a80, roughness: 0.36, metalness: 0.02,
    clearcoat: 1, clearcoatRoughness: 0.06,
    sheen: 0.18, sheenColor: new THREE.Color(0x79f2e4), sheenRoughness: 0.5,
  });
  const tile = new THREE.Mesh(tileGeo, tileMat);
  icon.add(tile);

  // The "W": the same five points make_icon.py draws, stroke 21/256, round joins, butt ends.
  const glyphMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.22, roughness: 0.2, metalness: 0 });
  const wPts = [[46.08, 76.8], [64.853, 179.2], [89.6, 115.2], [131.413, 179.2], [148.48, 76.8]];
  const rW = (21 / 256) * S / 2;
  const zG = front + rW * 0.25;
  const pts = wPts.map(([x, y]) => new THREE.Vector3(px(x), py(y), zG));
  const up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i]; const b = pts[i + 1];
    const seg = new THREE.Mesh(new THREE.CylinderGeometry(rW, rW, a.distanceTo(b), 28, 1), glyphMat);
    seg.position.copy(a).lerp(b, 0.5);
    seg.quaternion.setFromUnitVectors(up, b.clone().sub(a).normalize());
    icon.add(seg);
  }
  for (let i = 1; i < pts.length - 1; i++) {
    const joint = new THREE.Mesh(new THREE.SphereGeometry(rW, 28, 16), glyphMat);
    joint.position.copy(pts[i]);
    icon.add(joint);
  }

  // Three sound arcs: centre (199.68, 128), radii 20.48 / 35.84 / 51.2, width 10, spanning ±50°.
  const arcW = (10 / 256) * S;
  const arcs = [20.48, 35.84, 51.2].map((r) => {
    const mat = glyphMat.clone();
    const mesh = new THREE.Mesh(new THREE.TorusGeometry(((r - 5) / 256) * S, arcW / 2, 14, 56, THREE.MathUtils.degToRad(100)), mat);
    mesh.rotation.z = THREE.MathUtils.degToRad(-50);
    mesh.position.set(px(199.68), py(128), front + arcW * 0.1);
    icon.add(mesh);
    return mesh;
  });

  // Soft light behind the tile.
  const glowCol = srgb('#4ae2d2');
  const halo = new THREE.Mesh(
    new THREE.PlaneGeometry(8, 8),
    new THREE.ShaderMaterial({
      uniforms: { uColor: { value: glowCol }, uIntensity: { value: 0.5 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: 'uniform vec3 uColor; uniform float uIntensity; varying vec2 vUv; void main(){ float d = length(vUv - 0.5) * 2.0; float a = pow(max(0.0, 1.0 - d), 2.8) * uIntensity; gl_FragColor = vec4(uColor * a, a); }',
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }),
  );
  halo.position.set(0.1, TILE_Y, -1.4);
  rig.add(halo);

  /* ---------- Speech: a deterministic phrase/syllable envelope per column ---------- */
  const COLS = coarsePointer ? 170 : 260;
  const PER_COL = coarsePointer ? 22 : 38;
  const amps = speechEnvelope(COLS, 20260913);

  const nPts = COLS * PER_COL;
  const aCol = new Float32Array(nPts);
  const aRow = new Float32Array(nPts);
  const aAmp = new Float32Array(nPts);
  const aJit = new Float32Array(nPts * 3);
  let seed = 99;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let c = 0, k = 0; c < COLS; c++) {
    for (let r = 0; r < PER_COL; r++, k++) {
      aCol[k] = c / COLS;
      aRow[k] = (r / (PER_COL - 1)) * 2 - 1 + (rnd() - 0.5) * (1.6 / PER_COL);
      aAmp[k] = amps[c];
      aJit[k * 3] = rnd() - 0.5; aJit[k * 3 + 1] = rnd() - 0.5; aJit[k * 3 + 2] = rnd() - 0.5;
    }
  }
  const ribbonGeo = new THREE.BufferGeometry();
  ribbonGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(nPts * 3), 3));
  ribbonGeo.setAttribute('aCol', new THREE.BufferAttribute(aCol, 1));
  ribbonGeo.setAttribute('aRow', new THREE.BufferAttribute(aRow, 1));
  ribbonGeo.setAttribute('aAmp', new THREE.BufferAttribute(aAmp, 1));
  ribbonGeo.setAttribute('aJit', new THREE.BufferAttribute(aJit, 3));
  ribbonGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(-3, 0, -2), 12);

  const pointUniforms = { uViewportH: { value: 1 }, uFovTan: { value: Math.tan(THREE.MathUtils.degToRad(16)) } };
  const SPEED = 1 / 28;
  const ribbonMat = new THREE.ShaderMaterial({
    uniforms: {
      ...pointUniforms,
      uTime: { value: 0 },
      uSpeed: { value: SPEED },
      uP0: { value: new THREE.Vector3(9.0, -2.1, -3.2) },
      uP1: { value: new THREE.Vector3(4.1, -2.05, 0.9) },
      uP2: { value: new THREE.Vector3((S / 2) + 0.08, TILE_Y, 0.08) },
      uHeight: { value: 0.78 },
      uDeep: { value: srgb('#0f5a5e') },
      uGlow: { value: glowCol },
      uHot: { value: srgb('#dcfffa') },
      uOpacity: { value: 1 },
      uBurst: { value: 0 },
    },
    vertexShader: /* glsl */`
      uniform float uTime, uSpeed, uHeight, uViewportH, uFovTan, uBurst;
      uniform vec3 uP0, uP1, uP2;
      attribute float aCol, aRow, aAmp;
      attribute vec3 aJit;
      varying float vAlpha, vEnergy, vFlow;
      vec3 bez(float t){ float s = 1.0 - t; return s*s*uP0 + 2.0*s*t*uP1 + t*t*uP2; }
      vec3 bezD(float t){ return 2.0*(1.0 - t)*(uP1 - uP0) + 2.0*t*(uP2 - uP1); }
      void main(){
        float flow = fract(aCol + uTime * uSpeed);
        float taperIn = smoothstep(0.0, 0.16, flow);
        float squeeze = 1.0 - smoothstep(0.84, 1.0, flow);
        vec3 p = bez(flow);
        vec3 tng = normalize(bezD(flow));
        vec3 side = normalize(cross(tng, vec3(0.0, 1.0, 0.0)));
        float amp = aAmp * (1.0 + uBurst * 0.35);
        float h = aRow * amp * uHeight * squeeze * taperIn;
        p += vec3(0.0, h, 0.0) + side * aJit.z * 0.05 * squeeze + aJit * 0.007;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        float energy = amp * (1.0 - abs(aRow) * 0.5);
        float worldSize = 0.026 + energy * 0.03;
        gl_PointSize = max(1.0, worldSize * uViewportH * 0.5 / (uFovTan * -mv.z));
        float quiet = mix(0.12, 1.0, smoothstep(0.02, 0.25, aAmp));
        vAlpha = taperIn * quiet * (0.35 + 0.65 * (1.0 - abs(aRow) * 0.6));
        vEnergy = energy; vFlow = flow;
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 uDeep, uGlow, uHot;
      uniform float uOpacity;
      varying float vAlpha, vEnergy, vFlow;
      void main(){
        float d = length(gl_PointCoord - 0.5);
        float core = smoothstep(0.5, 0.0, d);
        vec3 col = mix(uDeep, uGlow, smoothstep(0.05, 0.75, vEnergy));
        col = mix(col, uHot, smoothstep(0.92, 1.0, vFlow) * 0.8);
        float a = core * core * vAlpha * uOpacity;
        gl_FragColor = vec4(col * a, a);
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const ribbon = new THREE.Points(ribbonGeo, ribbonMat);
  ribbon.frustumCulled = false;
  rig.add(ribbon);

  /* ---------- Dust: depth cue ---------- */
  const DUST = coarsePointer ? 260 : 620;
  const dustPos = new Float32Array(DUST * 3);
  const dustSeed = new Float32Array(DUST);
  for (let i = 0; i < DUST; i++) {
    dustPos[i * 3] = (rnd() - 0.4) * 22; dustPos[i * 3 + 1] = (rnd() - 0.5) * 11; dustPos[i * 3 + 2] = -rnd() * 14 + 3;
    dustSeed[i] = rnd();
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  dustGeo.setAttribute('aSeed', new THREE.BufferAttribute(dustSeed, 1));
  const dustMat = new THREE.ShaderMaterial({
    uniforms: { ...pointUniforms, uTime: { value: 0 }, uColor: { value: srgb('#9ff5ea') }, uOpacity: { value: 1 } },
    vertexShader: /* glsl */`
      uniform float uTime, uViewportH, uFovTan;
      attribute float aSeed;
      varying float vA;
      void main(){
        vec3 p = position;
        p.y = mod(p.y + uTime * (0.03 + aSeed * 0.07) + 5.5, 11.0) - 5.5;
        p.x += sin(uTime * 0.2 + aSeed * 40.0) * 0.15;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = max(1.0, (0.015 + aSeed * 0.035) * uViewportH * 0.5 / (uFovTan * -mv.z));
        vA = (0.08 + aSeed * 0.28) * smoothstep(5.5, 3.5, abs(p.y));
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 uColor; uniform float uOpacity; varying float vA;
      void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * vA * uOpacity; gl_FragColor = vec4(uColor * a, a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const dust = new THREE.Points(dustGeo, dustMat);
  dust.frustumCulled = false;
  rig.add(dust);

  /* ---------- SRT cues rising out of the icon ---------- */
  await Promise.race([
    Promise.all([document.fonts.load('600 56px Sora'), document.fonts.load('500 30px "Geist Mono"')]),
    new Promise((r) => setTimeout(r, 1800)),
  ]).catch(() => {});

  const LINES = [
    'Drag in audio or video.',
    'Whisper runs on your own machine.',
    'No cloud. No account. No upload.',
    'SRT, VTT, DOCX, PDF — 14 formats.',
    'Who said what, word by word.',
    'Live mic? Transcribed as you speak.',
    'Bonjour — le français aussi.',
    'Free and open source.',
  ];
  const CUE_W = 2.2;
  const CUE_H = CUE_W * (232 / 1024);
  const CUE_LIFE = 6.0;
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  const cueGeo = new THREE.PlaneGeometry(CUE_W, CUE_H);
  const pool = Array.from({ length: 5 }, () => {
    const cv = document.createElement('canvas');
    cv.width = 1024; cv.height = 232;
    const tex = new THREE.CanvasTexture(cv);
    tex.anisotropy = maxAniso;
    const mat = new THREE.ShaderMaterial({
      uniforms: { uMap: { value: tex }, uOpacity: { value: 0 }, uReveal: { value: 0 }, uTextStart: { value: 0.04 }, uTextEnd: { value: 0.9 }, uGlow: { value: glowCol } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: /* glsl */`
        uniform sampler2D uMap; uniform float uOpacity, uReveal, uTextStart, uTextEnd; uniform vec3 uGlow;
        varying vec2 vUv;
        void main(){
          vec4 t = texture2D(uMap, vUv);
          float textBand = step(vUv.y, 0.52) * step(0.12, vUv.y);
          float edge = mix(uTextStart, uTextEnd, uReveal);
          float shown = 1.0 - smoothstep(edge - 0.003, edge + 0.003, vUv.x);
          float a = t.a * mix(1.0, shown, textBand);
          float typing = step(uReveal, 0.995) * step(0.001, uReveal);
          float caret = textBand * typing * (1.0 - smoothstep(0.0, 0.0045, abs(vUv.x - edge)));
          vec3 col = mix(t.rgb, uGlow, caret);
          gl_FragColor = vec4(col, max(a, caret) * uOpacity);
        }`,
      transparent: true, depthWrite: false,
    });
    const mesh = new THREE.Mesh(cueGeo, mat);
    mesh.visible = false;
    mesh.renderOrder = 5;
    rig.add(mesh);
    return { mesh, mat, tex, cv, birth: -1e9, drift: 0 };
  });

  let cueIndex = 0;
  let srtClock = 1.12; // seconds
  const fmt = (sec) => {
    const ms = Math.round(sec * 1000);
    const h = Math.floor(ms / 3600000); const m = Math.floor(ms / 60000) % 60; const s = Math.floor(ms / 1000) % 60; const r = ms % 1000;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(r).padStart(3, '0')}`;
  };

  function drawCue(slot, n, start, end, text) {
    const g = slot.cv.getContext('2d');
    const W = slot.cv.width; const H = slot.cv.height;
    g.clearRect(0, 0, W, H);
    roundRect(g, 4, 4, W - 8, H - 8, 36);
    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, 'rgba(14, 32, 33, 0.9)');
    bg.addColorStop(1, 'rgba(6, 15, 16, 0.86)');
    g.fillStyle = bg; g.fill();
    g.lineWidth = 3; g.strokeStyle = 'rgba(143, 245, 233, 0.30)'; g.stroke();
    g.textBaseline = 'alphabetic';
    g.font = '500 29px "Geist Mono", ui-monospace, monospace';
    g.fillStyle = 'rgba(74, 226, 210, 1)';
    g.fillText(String(n), 46, 76);
    const nW = g.measureText(String(n)).width;
    g.fillStyle = 'rgba(162, 181, 179, 0.9)';
    g.fillText(`${start} --> ${end}`, 46 + nW + 26, 76);
    let size = 58;
    const setFont = () => { g.font = `600 ${size}px Sora, Geist, system-ui, sans-serif`; };
    setFont();
    while (g.measureText(text).width > W - 96 && size > 30) { size -= 2; setFont(); }
    g.fillStyle = '#eef6f5';
    g.fillText(text, 46, 172);
    slot.mat.uniforms.uTextStart.value = 44 / W;
    slot.mat.uniforms.uTextEnd.value = (50 + g.measureText(text).width) / W;
    slot.tex.needsUpdate = true;
  }

  function spawnCue(now) {
    const slot = pool.reduce((best, s) => (s.birth < best.birth ? s : best), pool[0]);
    const text = LINES[cueIndex % LINES.length];
    const dur = 1.9 + text.length * 0.045;
    drawCue(slot, cueIndex + 1, fmt(srtClock), fmt(srtClock + dur), text);
    srtClock += dur + 0.24;
    cueIndex++;
    slot.birth = now;
    slot.drift = (cueIndex % 2 ? 1 : -1);
    slot.mesh.visible = true;
    if (isDebug) console.log(`[hero3d debug] spawn #${cueIndex} slot=${pool.indexOf(slot)} birth=${now.toFixed(2)} "${text}"`);
  }

  /* ---------- Layout: frame the scene around the copy ---------- */
  const frame = { ndcX: 0.3, ndcY: 0.04, dist: 11.5, scale: 1, portrait: false, cueScale: 1 };
  function layout() {
    const w = canvas.clientWidth || innerWidth;
    const h = canvas.clientHeight || innerHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, dprCap));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const aspect = w / h;
    frame.portrait = aspect < 0.95;
    if (frame.portrait) {
      Object.assign(frame, { ndcX: 0.0, ndcY: 0.5, dist: 12.5, scale: clamp(aspect * 1.25, 0.5, 0.8) });
    } else if (aspect < 1.35) {
      Object.assign(frame, { ndcX: 0.42, ndcY: 0.05, dist: 12.5, scale: 0.78 });
    } else {
      Object.assign(frame, { ndcX: 0.3, ndcY: 0.04, dist: 11.5, scale: 1 });
    }
    // The cue cards' travel and size were tuned against the wide desktop frame. halfW shrinks
    // with aspect faster than frame.scale does, so on narrower/shorter frames the same local
    // travel pushes cards past the canvas edge and up under the header. cueScale pulls both
    // back in proportionally for narrow/short frames; 1 leaves the validated desktop look alone.
    frame.cueScale = clamp(aspect / 1.2, 0.45, 1);
    rig.scale.setScalar(frame.scale);
    const vh = renderer.domElement.height;
    pointUniforms.uViewportH.value = vh;
    ribbonMat.uniforms.uViewportH.value = vh;
    dustMat.uniforms.uViewportH.value = vh;
  }

  /* ---------- Input ---------- */
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  addEventListener('pointermove', (e) => {
    pointer.tx = (e.clientX / innerWidth) * 2 - 1;
    pointer.ty = (e.clientY / innerHeight) * 2 - 1;
  }, { passive: true });

  let scrollP = 0;
  const onScroll = () => {
    const r = hero.getBoundingClientRect();
    scrollP = clamp(-r.top / Math.max(1, r.height), 0, 1);
    hero.style.setProperty('--hero-fade', (1 - smooth(0.45, 0.95, scrollP)).toFixed(3));
  };
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let burst = 0;
  let hoverTile = false;
  const hitTile = (clientX, clientY) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    return raycaster.intersectObject(tile, false).length > 0;
  };
  hero.addEventListener('click', (e) => {
    if (e.target.closest('a, button')) return;
    if (hitTile(e.clientX, e.clientY)) { burst = 1; spawnCue(time); }
  });
  if (!coarsePointer) {
    hero.addEventListener('pointermove', (e) => {
      const over = !e.target.closest('a, button, p, h1') && hitTile(e.clientX, e.clientY);
      if (over !== hoverTile) { hoverTile = over; hero.style.cursor = over ? 'pointer' : ''; }
    }, { passive: true });
  }

  /* ---------- Update ---------- */
  const lookTarget = new THREE.Vector3();
  let time = reduceMotion ? 9.5 : 0;
  let lastHitAmp = 0;
  let lastSpawn = -10;
  let lastDebugLog = -10;

  function ampAtIcon(t) {
    const c = Math.floor((((0.965 - t * SPEED) % 1) + 1) % 1 * COLS) % COLS;
    return amps[c];
  }

  function update(dt) {
    // Speech arriving at the icon drives the arcs and the cue emission.
    const amp = ampAtIcon(time);
    burst = Math.max(0, burst - dt * 1.4);
    arcs.forEach((arc, i) => {
      const lag = ampAtIcon(time - (i + 1) * 0.35);
      arc.material.emissiveIntensity = 0.18 + lag * 1.4 + burst * (1.2 - i * 0.25);
    });
    halo.material.uniforms.uIntensity.value = 0.5 + amp * 0.4 + burst * 0.5;
    glyphMat.emissiveIntensity = 0.16 + amp * 0.18 + (hoverTile ? 0.25 : 0);
    // Onset crossings alone leave the cue stack empty for seconds at a time: the 3-tap
    // envelope smoothing keeps amplitude above the 0.42 threshold for an entire phrase, so a
    // crossing only happens once per phrase (~3-7s apart). A cadence fallback fills the gaps
    // whenever speech-like amplitude is sustained but hasn't re-crossed the onset threshold.
    const onset = amp > 0.42 && lastHitAmp <= 0.42 && time - lastSpawn > 1.2;
    const cadence = amp > 0.2 && time - lastSpawn > 2.4;
    if (!reduceMotion && (onset || cadence)) {
      spawnCue(time);
      lastSpawn = time;
    }
    lastHitAmp = amp;

    ribbonMat.uniforms.uTime.value = time;
    ribbonMat.uniforms.uBurst.value = burst;
    dustMat.uniforms.uTime.value = time;

    // Cues rise from the icon's upper-right corner and fade near the top of the frame.
    for (const slot of pool) {
      const age = (time - slot.birth) / CUE_LIFE;
      if (age < 0 || age > 1) { slot.mesh.visible = false; continue; }
      slot.mesh.visible = true;
      const e = easeOut(age / 0.22);
      const spread = frame.cueScale;
      const x = (THREE.MathUtils.lerp(0.35, 0.95, e) + age * 0.22) * spread + slot.drift * 0.03;
      const y = THREE.MathUtils.lerp(TILE_Y + 0.5, TILE_Y + 1.25, e) + age * 1.85 * spread;
      const z = THREE.MathUtils.lerp(0.2, 0.75, e) + age * 0.5;
      slot.mesh.position.set(x, y, z);
      slot.mesh.scale.setScalar(THREE.MathUtils.lerp(0.45, 1, e) * spread);
      slot.mesh.rotation.set(-0.06, -0.34 + age * 0.08, 0.012 * slot.drift);
      slot.mat.uniforms.uReveal.value = clamp((age - 0.05) / 0.3, 0, 1);
      slot.mat.uniforms.uOpacity.value = smooth(0.0, 0.06, age) * (1 - smooth(0.66, 0.96, age));
    }
    if (isDebug && time - lastDebugLog > 1) {
      lastDebugLog = time;
      console.log(`[hero3d debug] t=${time.toFixed(2)} amp=${amp.toFixed(2)}`, pool.map((s, i) => ({
        slot: i, birth: +s.birth.toFixed(2), age: +((time - s.birth) / CUE_LIFE).toFixed(2), visible: s.mesh.visible,
      })));
    }

    // Camera: frame + parallax + scroll dolly.
    pointer.x = damp(pointer.x, reduceMotion ? 0 : pointer.tx, 3, dt);
    pointer.y = damp(pointer.y, reduceMotion ? 0 : pointer.ty, 3, dt);
    const dist = frame.dist * (1 - 0.14 * scrollP);
    const halfH = dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const halfW = halfH * camera.aspect;
    lookTarget.set(-frame.ndcX * halfW, -frame.ndcY * halfH + scrollP * 0.6, 0);
    camera.position.set(lookTarget.x + pointer.x * 0.45, lookTarget.y + 0.25 - pointer.y * 0.3, dist);
    camera.lookAt(lookTarget);

    const floatY = reduceMotion ? 0 : Math.sin(time * 0.8) * 0.05;
    icon.position.y = TILE_Y + floatY;
    icon.rotation.y = damp(icon.rotation.y, -0.3 + pointer.x * 0.22 + (reduceMotion ? 0 : Math.sin(time * 0.35) * 0.05), 4, dt);
    icon.rotation.x = damp(icon.rotation.x, 0.06 + pointer.y * 0.12 - scrollP * 0.3, 4, dt);
    halo.position.y = TILE_Y + floatY;
    rig.rotation.y = damp(rig.rotation.y, pointer.x * 0.05, 2, dt);
  }

  /* ---------- Loop with visibility + adaptive quality ---------- */
  const clock = new THREE.Clock();
  let raf = 0;
  let inView = true;
  let frames = 0;
  let slowFrames = 0;
  let degraded = false;

  function render() {
    renderer.render(scene, camera);
  }

  function tick() {
    raf = requestAnimationFrame(tick);
    const dt = Math.min(clock.getDelta(), 1 / 20);
    time += dt;
    update(dt);
    render();
    frames++;
    if (!degraded && frames > 45 && frames < 240) {
      if (dt > 1 / 38) slowFrames++;
      if (slowFrames > 60) {
        degraded = true;
        dprCap = 1;
        ribbonGeo.setDrawRange(0, Math.floor(nPts * 0.55));
        layout();
      }
    }
  }

  function play() {
    if (raf || reduceMotion || !inView || document.hidden) return;
    clock.getDelta();
    raf = requestAnimationFrame(tick);
  }
  function pause() {
    cancelAnimationFrame(raf);
    raf = 0;
  }

  layout();

  if (isStill) {
    spawnCue(-2.2);
    for (let s = 0; s <= stillAt; s += 1 / 30) { time = s; update(1 / 30); }
    render();
    hero.classList.add('is-3d', 'is-still');
    new ResizeObserver(() => { layout(); update(0); render(); }).observe(canvas);
    return;
  }

  if (reduceMotion) {
    // One composed still: three cues already on screen, no motion.
    [0.12, 0.38, 0.62].forEach((age, i) => {
      spawnCue(time - age * CUE_LIFE);
      pool[i].birth = time - age * CUE_LIFE;
    });
  } else {
    spawnCue(time - 2.2);
  }
  update(1 / 60);
  render();
  hero.classList.add('is-3d');

  new ResizeObserver(() => { layout(); if (!raf) { update(0); render(); } }).observe(canvas);
  new IntersectionObserver(([entry]) => {
    inView = entry.isIntersecting;
    if (inView) play(); else pause();
  }).observe(hero);
  document.addEventListener('visibilitychange', () => (document.hidden ? pause() : play()));

  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); pause(); hero.classList.remove('is-3d'); });

  play();
}

/* ---------- helpers ---------- */
function roundedSquare(size, radius) {
  const h = size / 2; const r = radius; const s = new THREE.Shape();
  s.moveTo(-h + r, -h);
  s.lineTo(h - r, -h); s.absarc(h - r, -h + r, r, -Math.PI / 2, 0, false);
  s.lineTo(h, h - r); s.absarc(h - r, h - r, r, 0, Math.PI / 2, false);
  s.lineTo(-h + r, h); s.absarc(-h + r, h - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(-h, -h + r); s.absarc(-h + r, -h + r, r, Math.PI, Math.PI * 1.5, false);
  return s;
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

// Phrases separated by pauses; syllables with varied energy; lightly smoothed.
function speechEnvelope(cols, seed) {
  let s = seed % 2147483647;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const raw = new Float32Array(cols);
  let c = 0;
  while (c < cols) {
    const phrase = 22 + Math.floor(rnd() * 30);
    let p = 0;
    while (p < phrase && c < cols) {
      const syl = 3 + Math.floor(rnd() * 4);
      const energy = 0.45 + rnd() * 0.55;
      for (let k = 0; k < syl && p < phrase && c < cols; k++, p++, c++) {
        const win = Math.sin(Math.PI * (k + 0.5) / syl);
        const edge = Math.min(1, p / 5, (phrase - p) / 5);
        raw[c] = energy * win * (0.35 + 0.65 * edge);
      }
    }
    const pause = 7 + Math.floor(rnd() * 10);
    for (let k = 0; k < pause && c < cols; k++, c++) raw[c] = 0.015 * rnd();
  }
  const out = new Float32Array(cols);
  for (let i = 0; i < cols; i++) {
    const a = raw[(i - 1 + cols) % cols]; const b = raw[i]; const d = raw[(i + 1) % cols];
    out[i] = a * 0.22 + b * 0.56 + d * 0.22;
  }
  return out;
}
