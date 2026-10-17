// Geometry helpers: EPSG:2180 forward projection, polygons, coverage estimate.

const A = 6378137.0;
const F = 1 / 298.257222101; // GRS80
const E2 = 2 * F - F * F;
const EP2 = E2 / (1 - E2);
const K0 = 0.9993;
const LON0 = (19 * Math.PI) / 180;
const FE = 500000;
const FN = -5300000;

/** WGS84/ETRS89 lon, lat (degrees) -> EPSG:2180 [E, N] (Snyder's TM series). */
export function to2180([lon, lat]) {
  const phi = (lat * Math.PI) / 180;
  const lam = (lon * Math.PI) / 180;
  const sin = Math.sin(phi);
  const cos = Math.cos(phi);
  const tan = Math.tan(phi);
  const n = A / Math.sqrt(1 - E2 * sin * sin);
  const t = tan * tan;
  const c = EP2 * cos * cos;
  const a = (lam - LON0) * cos;
  const e4 = E2 * E2;
  const e6 = e4 * E2;
  const m =
    A *
    ((1 - E2 / 4 - (3 * e4) / 64 - (5 * e6) / 256) * phi -
      ((3 * E2) / 8 + (3 * e4) / 32 + (45 * e6) / 1024) * Math.sin(2 * phi) +
      ((15 * e4) / 256 + (45 * e6) / 1024) * Math.sin(4 * phi) -
      ((35 * e6) / 3072) * Math.sin(6 * phi));
  const x =
    FE +
    K0 * n * (a + ((1 - t + c) * a ** 3) / 6 + ((5 - 18 * t + t * t + 72 * c - 58 * EP2) * a ** 5) / 120);
  const y =
    FN +
    K0 *
      (m +
        n *
          tan *
          ((a * a) / 2 +
            ((5 - t + 9 * c + 4 * c * c) * a ** 4) / 24 +
            ((61 - 58 * t + t * t + 600 * c - 330 * EP2) * a ** 6) / 720));
  return [x, y];
}

export function bounds(ring) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of ring) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return [minX, minY, maxX, maxY];
}

/** Shoelace area of a planar ring (absolute). */
export function ringArea(ring) {
  let s = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    s += (ring[j][0] + ring[i][0]) * (ring[j][1] - ring[i][1]);
  }
  return Math.abs(s / 2);
}

export function inside([x, y], ring) {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

/** Whether every vertex of ring (EPSG:2180) lies inside bbox [w, s, e, n] (+tolerance). */
export function withinBox(ring, [w, s, e, n], tol = 5) {
  return ring.every(([x, y]) => x >= w - tol && x <= e + tol && y >= s - tol && y <= n + tol);
}

/**
 * Coverage of a user area estimated from the fixture sheet frames.
 *
 * The area (EPSG:2180 ring) is sampled on a grid of cell centres (about
 * `cells` along the longer side), like Kartograf's 1 m pixel grid but
 * coarser. For each combination: the share of area cells inside frames of
 * full sheets (lower bound, "full_m2"), inside any frame of the combination
 * (upper bound), the sheets that intersect the area and the campaigns of
 * their selected records. The whole demo area is land, so area = land.
 */
export function estimate(areaRing, combos, sheets, cells = 240) {
  const [minX, minY, maxX, maxY] = bounds(areaRing);
  const size = Math.max(maxX - minX, maxY - minY) / cells;
  const nx = Math.max(1, Math.ceil((maxX - minX) / size));
  const ny = Math.max(1, Math.ceil((maxY - minY) / size));
  const mask = new Uint8Array(nx * ny);
  let total = 0;
  for (let j = 0; j < ny; j++) {
    const y = minY + (j + 0.5) * size;
    for (let i = 0; i < nx; i++) {
      if (inside([minX + (i + 0.5) * size, y], areaRing)) {
        mask[j * nx + i] = 1;
        total++;
      }
    }
  }
  const areaM2 = ringArea(areaRing);
  const result = new Map();
  const full = new Uint8Array(nx * ny);
  const any = new Uint8Array(nx * ny);
  for (const combo of combos) {
    full.fill(0);
    any.fill(0);
    const hitFull = [];
    const hitPartial = [];
    const fullSet = new Set(combo.sheetsFull);
    for (const code of [...combo.sheetsFull, ...combo.sheetsPartial]) {
      const ring = sheets[code]?.ring2180;
      if (!ring) continue;
      const [sx0, sy0, sx1, sy1] = bounds(ring);
      const i0 = Math.max(0, Math.floor((sx0 - minX) / size));
      const i1 = Math.min(nx - 1, Math.floor((sx1 - minX) / size));
      const j0 = Math.max(0, Math.floor((sy0 - minY) / size));
      const j1 = Math.min(ny - 1, Math.floor((sy1 - minY) / size));
      let touched = false;
      for (let j = j0; j <= j1; j++) {
        const y = minY + (j + 0.5) * size;
        for (let i = i0; i <= i1; i++) {
          const k = j * nx + i;
          if (!mask[k] || !inside([minX + (i + 0.5) * size, y], ring)) continue;
          touched = true;
          any[k] = 1;
          if (fullSet.has(code)) full[k] = 1;
        }
      }
      if (touched) (fullSet.has(code) ? hitFull : hitPartial).push(code);
    }
    let nFull = 0;
    let nAny = 0;
    for (let k = 0; k < mask.length; k++) {
      nFull += full[k];
      nAny += any[k];
    }
    if (!hitFull.length && !hitPartial.length) {
      result.set(combo.id, null);
      continue;
    }
    const campaigns = new Set(
      hitFull.map((code) => combo.sheetRecords?.[code]?.campaign).filter(Boolean),
    );
    result.set(combo.id, {
      landM2: areaM2,
      fullM2: total ? (areaM2 * nFull) / total : 0,
      framesM2: total ? (areaM2 * nAny) / total : 0,
      complete: total > 0 && nFull === total,
      sheetsFull: hitFull.sort(),
      sheetsPartial: hitPartial.sort(),
      campaignsSelected: [...campaigns].sort(),
    });
  }
  return { areaM2, cells: total, result };
}
