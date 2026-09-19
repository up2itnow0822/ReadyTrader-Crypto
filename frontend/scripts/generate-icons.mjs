#!/usr/bin/env node
/**
 * Deterministically generates the PNG icons `public/manifest.json` references
 * (`public/icons/icon-192.png`, `public/icons/icon-512.png`) without adding any new
 * runtime or build dependency: this hand-rolls the tiny slice of the PNG format we
 * need (IHDR/IDAT/IEND with a raw CRC-32) and reuses Node's built-in `zlib` for the
 * DEFLATE compression PNG requires.
 *
 * Run with: `node scripts/generate-icons.mjs`
 */
import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, "..", "public", "icons");

const BG = [11, 17, 32]; // matches --color-bg
const BAR = [56, 189, 248]; // matches --color-accent

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const lenBuf = Buffer.alloc(4);
  lenBuf.writeUInt32BE(data.length, 0);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([lenBuf, typeBuf, data, crcBuf]);
}

/** A simple deterministic "bar chart" glyph: three bars of increasing height, centered. */
function pixelColor(x, y, size) {
  const barWidth = Math.round(size * 0.12);
  const gap = Math.round(size * 0.07);
  const baseline = Math.round(size * 0.78);
  const heights = [0.32, 0.52, 0.72].map((f) => Math.round(size * f));
  const totalWidth = barWidth * 3 + gap * 2;
  const startX = Math.round((size - totalWidth) / 2);

  for (let i = 0; i < 3; i++) {
    const barX0 = startX + i * (barWidth + gap);
    const barX1 = barX0 + barWidth;
    const barY0 = baseline - heights[i];
    if (x >= barX0 && x < barX1 && y >= barY0 && y < baseline) {
      return BAR;
    }
  }
  return BG;
}

function buildPng(size) {
  const raw = Buffer.alloc((size * 4 + 1) * size);
  let offset = 0;
  for (let y = 0; y < size; y++) {
    raw[offset] = 0; // filter type: None
    offset += 1;
    for (let x = 0; x < size; x++) {
      const [r, g, b] = pixelColor(x, y, size);
      raw[offset] = r;
      raw[offset + 1] = g;
      raw[offset + 2] = b;
      raw[offset + 3] = 255;
      offset += 4;
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type: RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const idat = deflateSync(raw);

  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return Buffer.concat([signature, chunk("IHDR", ihdr), chunk("IDAT", idat), chunk("IEND", Buffer.alloc(0))]);
}

mkdirSync(OUT_DIR, { recursive: true });
for (const size of [192, 512]) {
  const png = buildPng(size);
  const path = join(OUT_DIR, `icon-${size}.png`);
  writeFileSync(path, png);
  console.log(`Wrote ${path} (${png.length} bytes)`);
}
