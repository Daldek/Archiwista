/**
 * Geometry of the Wachlarz (docs/SPEC.md 5.4, 6.5 c; A-ADR-018 errata 1),
 * after the mockup (`mockup/src/fan.js`): the layers' thumbnails on an arc
 * like a stack in the macOS dock — the middle on the left, both ends to the
 * right — newest on top, the chosen one enlarged. Every thumbnail has a
 * vertical slot of its own sized from the stage, its rotation included, and
 * its caption stays within the slot, so nothing covers anything; with more
 * layers than the stage holds at the smallest size, the arc grows taller and
 * the stage scrolls. Where the stage has room, the chosen layer is also
 * large beside the captions.
 */

/** Enlargement of the chosen thumbnail on the arc. */
export const CHOSEN_SCALE = 1.9;
/** Stages narrower than this get narrow captions (a phone, a half screen). */
export const COMPACT_WIDTH = 780;
/** Sizes of the API's thumbnails (`size` of `thumbnail.png`), px. */
export const THUMBNAIL_SIZES = [128, 256, 512, 1024];

/** Gap between two slots, px. */
const GAP = 8;
/** Rotation of the outermost thumbnails, rad (about 5°). */
const TILT = 0.09;
/** Radius of the arc as a share of its height. */
const CURVE = 1.15;
/** The smallest thumbnail height, px: below it the arc outgrows the stage. */
const MIN_HEIGHT = 22;
/** Wide stages (ultrawide screens): larger thumbnails and a larger view. */
const WIDE_WIDTH = 1500;
const CAPTION_GAP = 16;
const PREVIEW_GAP = 40;
/** The large view is shown only when it is at least this wide, px. */
const PREVIEW_MIN = 220;
/** Height of the large view's title line above it and of its note below, px. */
export const PREVIEW_HEAD = 34;
export const PREVIEW_NOTE = 64;

/**
 * A box on the stage, px.
 *
 * @typedef {{x: number, y: number, width: number, height: number}} Box
 */

/**
 * A layer's place on the arc.
 *
 * @typedef {object} FanCard
 * @property {number} x - Left of the thumbnail before its rotation, px.
 * @property {number} y - Top of the thumbnail before its rotation, px.
 * @property {number} width
 * @property {number} height
 * @property {number} rotate - Rotation about the thumbnail's centre, rad.
 * @property {boolean} chosen
 * @property {Box} caption - The caption beside the thumbnail, within its slot.
 * @property {"full"|"short"|"line"} detail - What the caption has room for:
 *   every fact, the coverage and the variant, or the coverage alone.
 */

/**
 * The Wachlarz on a stage.
 *
 * @typedef {object} FanPlan
 * @property {FanCard[]} cards - In the order of the layers.
 * @property {Box|null} preview - The chosen layer's large thumbnail, its title
 *   line above it and its note below (`PREVIEW_HEAD`, `PREVIEW_NOTE`) not
 *   included; null without a chosen layer or room for it.
 * @property {number} height - Height of the content, px: the stage's, or more
 *   when the arc has to scroll.
 * @property {number} thumbnail - The `size` to ask for the arc's thumbnails.
 * @property {boolean} compact
 */

/**
 * Place the thumbnails, their captions and the large view.
 *
 * @param {object} input
 * @param {number} input.count - Layers, newest first.
 * @param {number} input.chosen - Index of the chosen layer, -1 for none.
 * @param {number} input.aspect - Height of a thumbnail over its width (the
 *   frame's).
 * @param {number} input.width - Width of the stage, px.
 * @param {number} input.height - Height of the stage, px.
 * @returns {FanPlan}
 */
export function fanLayout({ count, chosen, aspect, width, height }) {
  const compact = width < COMPACT_WIDTH;
  const wide = width >= WIDE_WIDTH;
  const top = compact ? 10 : 14;
  const bottom = compact ? 14 : 22;
  const span = Math.max(1, height - top - bottom);
  // Phones get the narrowest captions; a half screen or a stage beside the panels a little more.
  const captionWidth = width >= 1000 ? 340 : compact ? Math.max(150, Math.min(230, Math.round(width * 0.32))) : 260;
  // The horizontal swing of the arc is that of the stage's height, also when
  // the content scrolls: the ends never leave the stage on the right.
  const swing = span * curve(1);
  const picked = chosen >= 0 && chosen < count;
  const units = (count + (picked ? CHOSEN_SCALE - 1 : 0)) * (1 + Math.sin(TILT) / aspect);
  const fit = (span - Math.max(0, count - 1) * GAP) / units;
  const room = ((width - 40 - swing - CAPTION_GAP - captionWidth) / CHOSEN_SCALE) * aspect;
  const cardHeight = Math.max(MIN_HEIGHT, Math.min(wide ? 220 : 150, fit, room));
  const cardWidth = cardHeight / aspect;
  const slots = Array.from({ length: count }, (_, index) => {
    const scale = index === chosen ? CHOSEN_SCALE : 1;
    const box = { width: cardWidth * scale, height: cardHeight * scale };
    return { ...box, scale, slot: box.height + box.width * Math.sin(TILT) };
  });
  const total = slots.reduce((sum, slot) => sum + slot.slot, 0) + Math.max(0, count - 1) * GAP;
  const arc = Math.max(span, total);
  const block = swing + cardWidth * CHOSEN_SCALE + CAPTION_GAP + captionWidth;
  const previewWidth = picked
    ? Math.min(width - 24 - block - PREVIEW_GAP - 16, (span - PREVIEW_HEAD - PREVIEW_NOTE) / aspect, wide ? 1100 : 620)
    : 0;
  const preview = previewWidth >= PREVIEW_MIN;
  const left = preview
    ? Math.max(24, (width - block - PREVIEW_GAP - previewWidth) / 2)
    : Math.max(12, (width - block) / 2);
  const middle = top + arc / 2;
  let y = top + (arc - total) / 2;
  const cards = slots.map((slot) => {
    const centreY = y + slot.slot / 2;
    y += slot.slot + GAP;
    const along = Math.max(-1, Math.min(1, (centreY - middle) / (arc / 2)));
    const centreX = left + (swing * curve(along)) / curve(1) + (cardWidth * CHOSEN_SCALE) / 2;
    const chosenHere = slot.scale > 1;
    const captionHeight = Math.min(slot.slot, chosenHere ? 132 : 64);
    return {
      x: centreX - slot.width / 2,
      y: centreY - slot.height / 2,
      width: slot.width,
      height: slot.height,
      rotate: along * TILT,
      chosen: chosenHere,
      caption: {
        x: centreX + slot.width / 2 + CAPTION_GAP,
        y: centreY - captionHeight / 2,
        width: captionWidth,
        height: captionHeight,
      },
      detail: captionHeight >= 64 && (!compact || chosenHere) ? "full" : captionHeight >= 40 ? "short" : "line",
    };
  });
  let large = null;
  if (preview) {
    const card = cards[chosen];
    const previewHeight = previewWidth * aspect;
    const whole = PREVIEW_HEAD + previewHeight + PREVIEW_NOTE;
    const centreY = card.y + card.height / 2;
    const placed = Math.max(top, Math.min(top + arc - whole, centreY - whole / 2));
    large = { x: left + block + PREVIEW_GAP, y: placed + PREVIEW_HEAD, width: previewWidth, height: previewHeight };
  }
  return {
    cards,
    preview: large,
    height: top + arc + bottom,
    thumbnail: thumbnailSize(cardWidth * CHOSEN_SCALE, cardHeight * CHOSEN_SCALE),
    compact,
  };
}

/**
 * The `size` of a thumbnail drawn in a box: the smallest of the API's sizes
 * covering the box's longer side on this screen.
 *
 * @param {number} width - Box width, CSS px.
 * @param {number} height - Box height, CSS px.
 * @returns {number}
 */
export function thumbnailSize(width, height) {
  const needed = Math.max(width, height) * (window.devicePixelRatio || 1);
  return THUMBNAIL_SIZES.find((size) => size >= needed) ?? THUMBNAIL_SIZES[THUMBNAIL_SIZES.length - 1];
}

/**
 * How far right the arc runs at a point along it, as a share of its height:
 * a circle of radius `CURVE` × the height, zero in the middle (`along` 0),
 * the most at both ends (`along` ±1).
 *
 * @param {number} along - −1 (top) to 1 (bottom).
 * @returns {number}
 */
function curve(along) {
  return CURVE - Math.sqrt(CURVE * CURVE - (along / 2) ** 2);
}
