/*
 * Copyright 2025 MAX ROVENSKY
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 *
 * Separate optical layers and edge lighting adapted from rdev/liquid-glass-react.
 * Signed-distance lens map and DOM integration by Yanzhen.
 */
(() => {
  "use strict";
  const reducedTransparency = matchMedia(
    "(prefers-reduced-transparency: reduce)",
  );
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const chromium = /(?:Chrome|Chromium|Edg)\//.test(navigator.userAgent);
  const svgNS = "http://www.w3.org/2000/svg";
  const root = document.createElementNS(svgNS, "svg");
  root.setAttribute("aria-hidden", "true");
  root.setAttribute("width", "0");
  root.setAttribute("height", "0");
  root.style.cssText = "position:absolute;pointer-events:none;overflow:hidden";
  const defs = document.createElementNS(svgNS, "defs");
  root.append(defs);
  document.body.append(root);

  // A neutral center preserves the scene; only the rounded rim bends light.
  function lensMap(width, height, radius) {
    const ratio = Math.min(1, 720 / width, 720 / height);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(2, Math.round(width * ratio));
    canvas.height = Math.max(2, Math.round(height * ratio));
    const ctx = canvas.getContext("2d");
    const pixels = ctx.createImageData(canvas.width, canvas.height);
    const band = Math.min(14, height * 0.24);
    for (let y = 0; y < canvas.height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const px = (x + 0.5) / ratio - width / 2;
        const py = (y + 0.5) / ratio - height / 2;
        const qx = Math.abs(px) - (width / 2 - radius);
        const qy = Math.abs(py) - (height / 2 - radius);
        const ax = Math.max(qx, 0),
          ay = Math.max(qy, 0);
        const length = Math.hypot(ax, ay);
        const distance = length + Math.min(Math.max(qx, qy), 0) - radius;
        let nx = 0,
          ny = 0;
        if (length) {
          nx = (ax / length) * Math.sign(px);
          ny = (ay / length) * Math.sign(py);
        } else if (qx > qy) nx = Math.sign(px);
        else ny = Math.sign(py);
        const bend =
          distance <= 0 && distance > -band
            ? Math.pow(1 + distance / band, 2)
            : 0;
        const i = (y * canvas.width + x) * 4;
        pixels.data[i] = Math.round(128 + nx * bend * 110);
        pixels.data[i + 1] = Math.round(128 + ny * bend * 110);
        pixels.data[i + 2] = 128;
        pixels.data[i + 3] = 255;
      }
    }
    ctx.putImageData(pixels, 0, 0);
    return canvas.toDataURL();
  }

  const surfaces = [
    ...document.querySelectorAll(
      ".sidebar, .global-search, .chapter-rail, .theater-controls",
    ),
  ];
  surfaces.forEach((surface, index) => {
    surface.classList.add("liquid-surface");
    const filter = document.createElementNS(svgNS, "filter");
    const id = "yz-liquid-" + index;
    filter.id = id;
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", "100%");
    filter.setAttribute("height", "100%");
    filter.setAttribute("color-interpolation-filters", "sRGB");
    const map = document.createElementNS(svgNS, "feImage");
    map.setAttribute("result", "lens");
    map.setAttribute("width", "100%");
    map.setAttribute("height", "100%");
    map.setAttribute("preserveAspectRatio", "none");
    const displacement = document.createElementNS(svgNS, "feDisplacementMap");
    displacement.setAttribute("in", "SourceGraphic");
    displacement.setAttribute("in2", "lens");
    displacement.setAttribute("scale", "18");
    displacement.setAttribute("xChannelSelector", "R");
    displacement.setAttribute("yChannelSelector", "G");
    filter.append(map, displacement);
    defs.append(filter);
    let sizeKey = "",
      frame = 0;
    function update() {
      const { width, height } = surface.getBoundingClientRect();
      if (!width || !height || !chromium || reducedTransparency.matches) return;
      const style = getComputedStyle(surface);
      const key =
        Math.round(width) +
        ":" +
        Math.round(height) +
        ":" +
        style.getPropertyValue("--glass-blur");
      if (key === sizeKey) return;
      sizeKey = key;
      const radius = Math.min(parseFloat(style.borderRadius) || 26, height / 2);
      map.setAttribute("href", lensMap(width, height, radius));
      const blur = style.getPropertyValue("--glass-blur").trim() || "12px";
      surface.style.setProperty(
        "--optical-filter",
        `blur(${blur}) saturate(1.4) url(#${id})`,
      );
    }
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    });
    observer.observe(surface);
    surface.addEventListener("liquid-material-change", update);
    surface.addEventListener("pointermove", (event) => {
      if (reducedMotion.matches || event.pointerType === "touch") return;
      const rect = surface.getBoundingClientRect();
      const angle =
        (Math.atan2(
          event.clientY - rect.top - rect.height / 2,
          event.clientX - rect.left - rect.width / 2,
        ) *
          180) /
          Math.PI +
        90;
      surface.style.setProperty("--light-angle", angle.toFixed(1) + "deg");
    });
    surface.addEventListener("pointerleave", () =>
      surface.style.removeProperty("--light-angle"),
    );
    update();
  });
  function mode() {
    document.documentElement.classList.toggle(
      "liquid-optics",
      chromium && !reducedTransparency.matches,
    );
    // Recheck dimensions when a material preference changes without a resize.
    surfaces.forEach((surface) =>
      surface.dispatchEvent(new Event("liquid-material-change")),
    );
  }
  reducedTransparency.addEventListener("change", mode);
  mode();
})();
