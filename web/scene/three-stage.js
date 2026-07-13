"use strict";

import * as THREE from "../vendor/three.module.min.js";
import { cameraPreset, interpolateCamera, stageVisual } from "./transitions.js";

const STAGE_IDS = Object.freeze(["plan", "equip", "work", "guard", "prove"]);
const LAYER_LAYOUT = Object.freeze([
  { id: "intent", y: 3.2, z: -1.8 },
  { id: "control", y: 1.5, z: -0.6 },
  { id: "worker", y: -0.2, z: 0.6 },
  { id: "repo", y: -1.9, z: 1.8 },
]);
const RUNWAY_Y = -3.5;
const RUNWAY_Z = 2.7;
const CAMERA_TRANSITION_MS = 440;

const colorCss = color => `#${color.toString(16).padStart(6, "0")}`;

export function createThreeStage({ canvas, onStageSelected, reducedMotion = false }) {
  if (!canvas?.ownerDocument || typeof canvas.getBoundingClientRect !== "function") {
    throw new TypeError("A canvas element is required");
  }
  if (typeof onStageSelected !== "function") {
    throw new TypeError("onStageSelected must be a function");
  }

  const documentRef = canvas.ownerDocument;
  const windowRef = documentRef.defaultView;
  if (!windowRef?.requestAnimationFrame) {
    throw new Error("requestAnimationFrame is unavailable");
  }
  const requestFrame = windowRef.requestAnimationFrame.bind(windowRef);
  const cancelFrame = windowRef.cancelAnimationFrame.bind(windowRef);
  const now = () => windowRef.performance.now();

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 80);
  const cameraTarget = new THREE.Vector3();
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const runwayNodes = [];
  const stageAssets = new Map();
  const layerAssets = new Map();
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  let renderer = null;
  let animationRaf = null;
  let resizeRaf = null;
  let playbackActive = false;
  let transition = null;
  let selectedStageId = "plan";
  let disposed = false;

  const initialCamera = cameraPreset(selectedStageId);
  applyCamera(initialCamera);

  function trackGeometry(geometry) {
    geometries.add(geometry);
    return geometry;
  }

  function trackMaterial(material) {
    materials.add(material);
    return material;
  }

  function createLabel({ width, height, scale }) {
    const labelCanvas = documentRef.createElement("canvas");
    labelCanvas.width = width;
    labelCanvas.height = height;
    const context = labelCanvas.getContext("2d");
    if (!context) throw new Error("2D label canvas is unavailable");
    const texture = new THREE.CanvasTexture(labelCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = THREE.LinearFilter;
    textures.add(texture);
    const material = trackMaterial(new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    }));
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(...scale);
    return { canvas: labelCanvas, context, texture, sprite, value: "" };
  }

  function updateLabel(label, primary, secondary, visual) {
    const value = `${primary}\n${secondary}\n${visual.color}`;
    if (label.value === value) return;
    label.value = value;
    const { canvas: labelCanvas, context } = label;
    context.clearRect(0, 0, labelCanvas.width, labelCanvas.height);
    context.fillStyle = "rgba(15, 23, 42, 0.88)";
    context.fillRect(0, 0, labelCanvas.width, labelCanvas.height);
    context.strokeStyle = colorCss(visual.color);
    context.lineWidth = 5;
    context.strokeRect(3, 3, labelCanvas.width - 6, labelCanvas.height - 6);
    context.fillStyle = "#f8fafc";
    context.font = "600 34px Inter, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(primary, labelCanvas.width / 2, labelCanvas.height * 0.4);
    context.fillStyle = colorCss(visual.color);
    context.font = "500 22px Inter, sans-serif";
    context.fillText(secondary, labelCanvas.width / 2, labelCanvas.height * 0.73);
    label.texture.needsUpdate = true;
  }

  function createScene() {
    scene.add(new THREE.HemisphereLight(0xbfe9ff, 0x0f172a, 1.5));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.1);
    keyLight.position.set(2, 8, 12);
    scene.add(keyLight);

    const layerGeometry = trackGeometry(new THREE.PlaneGeometry(20, 1.2));
    for (const layer of LAYER_LAYOUT) {
      const material = trackMaterial(new THREE.MeshStandardMaterial({
        color: 0x334155,
        emissive: 0x0f172a,
        transparent: true,
        opacity: 0.12,
        depthWrite: false,
        side: THREE.DoubleSide,
      }));
      const mesh = new THREE.Mesh(layerGeometry, material);
      mesh.name = layer.id;
      mesh.position.set(0, layer.y, layer.z);
      mesh.rotation.x = -0.08;
      scene.add(mesh);

      const label = createLabel({ width: 512, height: 112, scale: [5.1, 1.12, 1] });
      label.sprite.position.set(-6.9, layer.y, layer.z + 0.08);
      scene.add(label.sprite);
      layerAssets.set(layer.id, { mesh, material, label });
    }

    const nodeGeometry = trackGeometry(new THREE.BoxGeometry(2.25, 0.78, 0.54));
    for (const [index, stageId] of STAGE_IDS.entries()) {
      const material = trackMaterial(new THREE.MeshStandardMaterial({
        color: 0x334155,
        emissive: 0x0f172a,
        transparent: true,
        opacity: 0.58,
        roughness: 0.36,
        metalness: 0.18,
      }));
      const mesh = new THREE.Mesh(nodeGeometry, material);
      mesh.name = stageId;
      mesh.userData.stageId = stageId;
      mesh.position.set(-8 + (index * 4), RUNWAY_Y, RUNWAY_Z);
      scene.add(mesh);
      runwayNodes.push(mesh);

      const label = createLabel({ width: 384, height: 128, scale: [3.1, 1.04, 1] });
      label.sprite.position.set(mesh.position.x, RUNWAY_Y + 1.05, RUNWAY_Z + 0.05);
      scene.add(label.sprite);
      stageAssets.set(stageId, { mesh, material, label });
    }

    const connectionPoints = runwayNodes.flatMap((node, index) => {
      if (index === runwayNodes.length - 1) return [];
      return [node.position.clone(), runwayNodes[index + 1].position.clone()];
    });
    const connectionGeometry = trackGeometry(
      new THREE.BufferGeometry().setFromPoints(connectionPoints),
    );
    const connectionMaterial = trackMaterial(new THREE.LineBasicMaterial({
      color: 0x64748b,
      transparent: true,
      opacity: 0.68,
    }));
    const connections = new THREE.LineSegments(connectionGeometry, connectionMaterial);
    connections.name = "runway-connections";
    scene.add(connections);
  }

  function currentCamera() {
    return {
      position: camera.position.toArray(),
      target: cameraTarget.toArray(),
    };
  }

  function applyCamera(cameraState) {
    camera.position.fromArray(cameraState.position);
    cameraTarget.fromArray(cameraState.target);
    camera.lookAt(cameraTarget);
  }

  function applySelectionScale(timestamp = 0) {
    for (const [stageId, asset] of stageAssets) {
      const selected = stageId === selectedStageId;
      const pulse = selected && playbackActive && !reducedMotion
        ? 1 + (Math.sin(timestamp / 180) * 0.035)
        : 1;
      const scale = (selected ? 1.12 : 1) * pulse;
      asset.mesh.scale.set(scale, scale, scale);
      asset.material.emissiveIntensity = selected ? 1.05 : 0.55;
    }
  }

  function updateTransition(timestamp) {
    if (!transition) return;
    const progress = (timestamp - transition.startedAt) / CAMERA_TRANSITION_MS;
    applyCamera(interpolateCamera(transition.from, transition.to, progress, reducedMotion));
    if (progress >= 1 || reducedMotion) transition = null;
  }

  function drawFrame(timestamp = now()) {
    if (disposed || documentRef.hidden || !renderer) return;
    updateTransition(timestamp);
    applySelectionScale(timestamp);
    renderer.render(scene, camera);
  }

  function shouldAnimate() {
    return Boolean(transition) || (playbackActive && !reducedMotion);
  }

  function stopAnimationLoop() {
    if (animationRaf === null) return;
    cancelFrame(animationRaf);
    animationRaf = null;
  }

  function animationFrame(timestamp) {
    animationRaf = null;
    if (disposed || documentRef.hidden) return;
    drawFrame(timestamp);
    syncAnimationLoop();
  }

  function syncAnimationLoop() {
    if (disposed || documentRef.hidden || !shouldAnimate()) {
      stopAnimationLoop();
      return;
    }
    if (animationRaf === null) animationRaf = requestFrame(animationFrame);
  }

  function performResize() {
    resizeRaf = null;
    if (disposed || !renderer) return;
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width || canvas.clientWidth || 1));
    const height = Math.max(1, Math.round(bounds.height || canvas.clientHeight || 1));
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    drawFrame();
  }

  function resize() {
    if (disposed || resizeRaf !== null) return;
    resizeRaf = requestFrame(performResize);
  }

  function handleVisibilityChange() {
    if (documentRef.hidden) {
      stopAnimationLoop();
      return;
    }
    drawFrame();
    syncAnimationLoop();
  }

  function handlePointerUp(event) {
    if (event.button !== 0 || disposed) return;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -(((event.clientY - bounds.top) / bounds.height) * 2 - 1),
    );
    raycaster.setFromCamera(pointer, camera);
    const [hit] = raycaster.intersectObjects(runwayNodes, false);
    if (hit) onStageSelected(hit.object.userData.stageId);
  }

  function render(viewModel) {
    if (!viewModel || !Array.isArray(viewModel.stages) || !viewModel.layers) {
      throw new TypeError("render requires a CockpitViewModel");
    }
    const stages = new Map(viewModel.stages.map(stage => [stage.id, stage]));
    for (const stageId of STAGE_IDS) {
      const stage = stages.get(stageId);
      if (!stage) throw new TypeError(`CockpitViewModel is missing stage: ${stageId}`);
      const visual = stageVisual(stage.status);
      const asset = stageAssets.get(stageId);
      asset.material.color.setHex(visual.color);
      asset.material.emissive.setHex(visual.emissive);
      asset.material.opacity = visual.opacity;
      updateLabel(asset.label, `${visual.glyph} ${stage.label}`, visual.label, visual);
    }

    const selectedLayer = stages.get(viewModel.selection?.stage)?.layer;
    for (const layer of LAYER_LAYOUT) {
      const model = viewModel.layers[layer.id];
      if (!model) throw new TypeError(`CockpitViewModel is missing layer: ${layer.id}`);
      const visual = stageVisual(model.status);
      const asset = layerAssets.get(layer.id);
      asset.material.color.setHex(visual.color);
      asset.material.emissive.setHex(visual.emissive);
      asset.material.opacity = visual.opacity * (layer.id === selectedLayer ? 0.3 : 0.15);
      asset.material.emissiveIntensity = layer.id === selectedLayer ? 0.75 : 0.25;
      updateLabel(asset.label, model.label, `${visual.glyph} ${visual.label}`, visual);
    }

    selectStage(viewModel.selection?.stage || "plan");
    drawFrame();
    syncAnimationLoop();
  }

  function selectStage(stageId) {
    if (!STAGE_IDS.includes(stageId)) return;
    if (stageId === selectedStageId) {
      applySelectionScale();
      return;
    }
    selectedStageId = stageId;
    const destination = cameraPreset(stageId);
    if (reducedMotion) {
      transition = null;
      applyCamera(destination);
    } else {
      transition = {
        from: currentCamera(),
        to: destination,
        startedAt: now(),
      };
    }
    applySelectionScale();
    drawFrame();
    syncAnimationLoop();
  }

  function setPlaybackActive(active) {
    playbackActive = Boolean(active);
    drawFrame();
    syncAnimationLoop();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stopAnimationLoop();
    if (resizeRaf !== null) {
      cancelFrame(resizeRaf);
      resizeRaf = null;
    }
    windowRef.removeEventListener("resize", resize);
    documentRef.removeEventListener("visibilitychange", handleVisibilityChange);
    canvas.removeEventListener("pointerup", handlePointerUp);
    scene.clear();
    for (const texture of textures) texture.dispose();
    for (const material of materials) material.dispose();
    for (const geometry of geometries) geometry.dispose();
    renderer?.renderLists?.dispose();
    renderer?.dispose();
    renderer?.forceContextLoss();
    renderer = null;
  }

  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(windowRef.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x0f172a, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    createScene();
    windowRef.addEventListener("resize", resize, { passive: true });
    documentRef.addEventListener("visibilitychange", handleVisibilityChange);
    canvas.addEventListener("pointerup", handlePointerUp);
    resize();
    drawFrame();
  } catch (error) {
    dispose();
    throw error;
  }

  return { render, selectStage, setPlaybackActive, resize, dispose };
}
