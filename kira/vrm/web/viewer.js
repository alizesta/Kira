import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const stage = document.getElementById("stage");
const statusNode = document.getElementById("status");
const params = new URLSearchParams(location.search);
const draggable = params.get("draggable") === "1";
let bridge = null;
let pendingBridgeEvent = null;
let vrm = null;
let renderer = null;
let camera = null;
let root = null;
let modelCenterY = 0;
let cameraDistance = 3.0;
let yaw = 0;
let pointer = null;
let lastTime = performance.now();
let elapsed = 0;
let frameState = { emotion: "neutral", blink: 0, mouth: 0, open: 0, speaking: 0, sleeping: false, look: [0,0] };
const baseBoneRotations = new Map();
const moodExpressions = ["happy", "sad", "angry", "surprised", "relaxed", "neutral"];
const mouthExpressions = ["aa", "ih", "ou", "ee", "oh"];
const expressionNames = new Set();

function reportError(message) {
  const text = String(message || "VRM viewer error").slice(0, 450);
  statusNode.textContent = text;
  statusNode.style.display = "block";
  if (bridge) bridge.onError(text);
  else pendingBridgeEvent = { kind: "error", text };
}

function reportReady() {
  statusNode.style.display = "none";
  if (bridge) bridge.onReady();
  else pendingBridgeEvent = { kind: "ready" };
}

if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.ai1;
    if (pendingBridgeEvent?.kind === "error") bridge.onError(pendingBridgeEvent.text);
    else if (pendingBridgeEvent?.kind === "ready") bridge.onReady();
    pendingBridgeEvent = null;
  });
} else {
  reportError("Qt WebChannel is unavailable. Reinstall the Qt WebEngine components.");
}

const scene = new THREE.Scene();
scene.background = null;
const ambient = new THREE.HemisphereLight(0xffffff, 0x8c789c, 1.45);
scene.add(ambient);
const keyLight = new THREE.DirectionalLight(0xffffff, 2.15);
keyLight.position.set(1.4, 2.6, 3.2);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xb8d9ff, 0.65);
fillLight.position.set(-2.2, 1.5, -2.5);
scene.add(fillLight);

camera = new THREE.PerspectiveCamera(29, 1, 0.05, 100);
camera.position.set(0, 1, 3);
camera.lookAt(0, 1, 0);

try {
  renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    premultipliedAlpha: false,
    powerPreference: "high-performance"
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.setClearColor(0x000000, 0);
  stage.appendChild(renderer.domElement);
} catch (error) {
  reportError("WebGL could not be initialized: " + (error?.message || error));
}

function setExpression(name, value) {
  if (!vrm?.expressionManager || !expressionNames.has(name)) return;
  vrm.expressionManager.setValue(name, THREE.MathUtils.clamp(value, 0, 1));
}

function captureBone(name) {
  const node = vrm?.humanoid?.getNormalizedBoneNode(name);
  if (node) baseBoneRotations.set(name, node.rotation.clone());
}

function updateBones() {
  const lookX = Number(frameState.look?.[0] || 0);
  const lookY = Number(frameState.look?.[1] || 0);
  const hips = vrm?.humanoid?.getNormalizedBoneNode("hips");
  const spine = vrm?.humanoid?.getNormalizedBoneNode("spine");
  const chest = vrm?.humanoid?.getNormalizedBoneNode("chest");
  const neck = vrm?.humanoid?.getNormalizedBoneNode("neck");
  const head = vrm?.humanoid?.getNormalizedBoneNode("head");
  const t = elapsed;
  const apply = (node, key, dx, dy, dz) => {
    const base = baseBoneRotations.get(key);
    if (!node || !base) return;
    node.rotation.set(base.x + dx, base.y + dy, base.z + dz, node.rotation.order);
  };
  apply(hips, "hips", Math.sin(t * 0.75) * 0.009, Math.sin(t * 0.42) * 0.025, Math.sin(t * 0.6) * 0.009);
  apply(spine, "spine", Math.sin(t * 0.85 + 0.5) * 0.012, Math.sin(t * 0.5) * 0.018, Math.sin(t * 0.65) * 0.008);
  apply(chest, "chest", Math.sin(t * 0.85 + 0.5) * 0.009, Math.sin(t * 0.48) * 0.012, 0);
  apply(neck, "neck", Math.sin(t * 0.5) * 0.012 + lookY * 0.035, lookX * 0.045, 0);
  apply(head, "head", Math.sin(t * 0.62 + 0.7) * 0.018 + lookY * 0.04,
    Math.sin(t * 0.38) * 0.035 + lookX * 0.085, Math.sin(t * 0.54) * 0.012);
  if (root) root.rotation.y = yaw + Math.sin(t * 0.22) * 0.012;
}

function applyFrame() {
  if (!vrm?.expressionManager) return;
  for (const name of moodExpressions) setExpression(name, 0);
  for (const name of mouthExpressions) setExpression(name, 0);
  setExpression("blink", frameState.blink || 0);
  setExpression("blinkLeft", frameState.blink || 0);
  setExpression("blinkRight", frameState.blink || 0);

  const emotionMap = {
    happy: ["happy", 0.72], excited: ["happy", 0.92], shy: ["happy", 0.34],
    sad: ["sad", 0.72], angry: ["angry", 0.76], surprised: ["surprised", 0.82],
    disgusted: ["angry", 0.28], playful: ["happy", 0.42], teasing: ["happy", 0.38],
    relaxed: ["relaxed", 0.42], sleepy: ["relaxed", 0.28], bored: ["relaxed", 0.2]
  };
  const mood = emotionMap[frameState.emotion];
  if (mood) setExpression(mood[0], mood[1]);

  const speech = Math.max(0.0, frameState.speaking || 0);
  const mouth = Math.max((frameState.mouth || 0) * speech, frameState.open || 0);
  if (mouth > 0.025) {
    if (speech < 0.035) {
      setExpression("aa", mouth * 0.55);
    } else {
      const phase = elapsed * 8.2;
      setExpression("aa", mouth * (0.44 + 0.22 * (0.5 + 0.5 * Math.sin(phase))));
      setExpression("ih", mouth * (0.16 + 0.15 * (0.5 + 0.5 * Math.sin(phase + 1.4))));
      setExpression("ou", mouth * (0.18 + 0.18 * (0.5 + 0.5 * Math.sin(phase + 2.2))));
      setExpression("ee", mouth * (0.12 + 0.14 * (0.5 + 0.5 * Math.sin(phase + 3.1))));
      setExpression("oh", mouth * (0.2 + 0.16 * (0.5 + 0.5 * Math.sin(phase + 4.0))));
    }
  }
}

function resize() {
  if (!renderer) return;
  const w = Math.max(1, stage.clientWidth);
  const h = Math.max(1, stage.clientHeight);
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

function regionFromPoint(x, y) {
  const normalized = y / Math.max(1, stage.clientHeight);
  if (normalized < 0.28) return "head";
  if (normalized < 0.58) return "torso";
  if (normalized > 0.76) return "legs";
  return "arms";
}

if (renderer) {
  renderer.domElement.addEventListener("pointerdown", (event) => {
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, lastX: event.clientX,
      lastY: event.clientY, moved: false, region: regionFromPoint(event.offsetX, event.offsetY) };
    renderer.domElement.setPointerCapture(event.pointerId);
  });
  renderer.domElement.addEventListener("pointermove", (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    const dx = event.clientX - pointer.lastX;
    const dy = event.clientY - pointer.lastY;
    if (Math.abs(event.clientX - pointer.x) + Math.abs(event.clientY - pointer.y) > 5) pointer.moved = true;
    if (pointer.moved) {
      if (draggable && bridge) bridge.onDrag(Math.round(dx), Math.round(dy));
      else yaw += dx * 0.008;
    }
    pointer.lastX = event.clientX;
    pointer.lastY = event.clientY;
  });
  const endPointer = (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (!pointer.moved && bridge) bridge.onClicked(pointer.region);
    pointer = null;
  };
  renderer.domElement.addEventListener("pointerup", endPointer);
  renderer.domElement.addEventListener("pointercancel", () => { pointer = null; });
  renderer.domElement.addEventListener("wheel", (event) => {
    cameraDistance = THREE.MathUtils.clamp(cameraDistance + event.deltaY * 0.0025, 1.1, 8.0);
    if (vrm) {
      const targetY = modelCenterY;
      camera.position.set(0, targetY, cameraDistance);
      camera.lookAt(0, targetY, 0);
    }
    event.preventDefault();
  }, { passive: false });
}

window.ai1SetFrame = (state) => {
  frameState = { ...frameState, ...(state || {}) };
};

async function loadModel() {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync("/model.vrm");
  vrm = gltf.userData.vrm;
  if (!vrm) throw new Error("No VRM extension was found in the selected model.");
  VRMUtils.rotateVRM0(vrm);
  root = vrm.scene;
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  if (!Number.isFinite(size.y) || size.y <= 0) throw new Error("The VRM model has invalid dimensions.");
  const center = box.getCenter(new THREE.Vector3());
  root.position.set(-center.x, -box.min.y, -center.z);
  modelCenterY = size.y * 0.52;
  cameraDistance = Math.max(1.5, size.y * 1.95);
  camera.position.set(0, modelCenterY, cameraDistance);
  camera.lookAt(0, modelCenterY, 0);

  for (const name of ["hips", "spine", "chest", "neck", "head"]) captureBone(name);
  for (const name of ["blink", "blinkLeft", "blinkRight", ...moodExpressions, ...mouthExpressions]) {
    if (vrm.expressionManager?.getExpression(name)) expressionNames.add(name);
  }
  resize();
  reportReady();
}

async function animate(now) {
  requestAnimationFrame(animate);
  if (!renderer) return;
  const dt = Math.min(0.05, Math.max(0, (now - lastTime) / 1000));
  lastTime = now;
  elapsed += dt;
  if (vrm) {
    applyFrame();
    updateBones();
    vrm.update(dt);
    renderer.render(scene, camera);
  }
}
requestAnimationFrame(animate);

loadModel().catch((error) => reportError(error?.message || error));
