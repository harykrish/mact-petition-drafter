/**
 * Automated demo video generator for Cambrian.
 *
 * Uses Puppeteer to screenshot the intro slide + live replay,
 * then ffmpeg to stitch frames with the voiceover into an mp4.
 *
 * Usage: node demo/record.mjs [--url URL]
 */

import puppeteer from 'puppeteer';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRAMES_DIR = path.join(__dirname, 'frames');
const OUTPUT = path.join(__dirname, 'demo.mp4');
const VOICEOVER = path.join(__dirname, 'voiceover_v2.mp3');
const SLIDE = path.join(__dirname, 'slide.html');
const BASE_URL = process.argv.includes('--url')
  ? process.argv[process.argv.indexOf('--url') + 1]
  : 'https://mact-petition-drafter.onrender.com';

const FPS = 4;  // frames per second — enough for a UI walkthrough
const W = 1920;
const H = 1080;

// Clean / create frames dir
if (fs.existsSync(FRAMES_DIR)) fs.rmSync(FRAMES_DIR, { recursive: true });
fs.mkdirSync(FRAMES_DIR);

let frameNum = 0;
function framePath() {
  return path.join(FRAMES_DIR, `frame_${String(frameNum++).padStart(5, '0')}.png`);
}

async function screenshot(page, duration = 1) {
  const count = Math.round(duration * FPS);
  const p = framePath();
  await page.screenshot({ path: p });
  // Duplicate the frame for the duration
  for (let i = 1; i < count; i++) {
    fs.copyFileSync(p, framePath());
  }
}

async function screenshotLive(page, duration = 1) {
  // Take actual screenshots at FPS intervals for animated content
  const count = Math.round(duration * FPS);
  for (let i = 0; i < count; i++) {
    await page.screenshot({ path: framePath() });
    await sleep(1000 / FPS);
  }
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  console.log('Launching browser...');
  const browser = await puppeteer.launch({
    headless: true,
    defaultViewport: { width: W, height: H },
    args: ['--no-sandbox', '--window-size=1920,1080']
  });

  const page = await browser.newPage();

  // ── Intro slide (30s) — holds for entire opening narration ──
  // "Every 24 seconds..." through "...today demoing the legal agent. Watch."
  console.log('1/6  Intro slide (30s — full opening narration)...');
  await page.goto(`file://${SLIDE}`, { waitUntil: 'networkidle2' });
  await sleep(500);
  await screenshot(page, 30);

  // Pre-load the app in background so it's ready for the cut
  console.log('2/6  Loading app...');
  await page.goto(BASE_URL, { waitUntil: 'networkidle2' });
  await sleep(1500);

  // ── Click Replay — ingestion (~15s) — "Nine documents go in..." ──
  console.log('3/6  Replay — ingestion...');
  await page.click('#homeReplay');
  await sleep(500);
  await screenshotLive(page, 15);

  // ── Contradiction panel (6s) — "The police report says March fifth..." ──
  console.log('4/6  Contradictions + KB verify...');
  await page.evaluate(() => {
    const cp = document.getElementById('contradictions');
    if (cp) cp.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await sleep(400);
  await screenshotLive(page, 6);

  // KB verify
  await page.evaluate(() => {
    const kb = document.getElementById('kbVerify');
    if (kb) kb.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await sleep(400);
  await screenshotLive(page, 5);

  // ── Drafting + petition tab — "Claude drafts the full petition..." ──
  console.log('5/6  Drafting + petition tab...');
  await screenshotLive(page, 8);

  // Click petition tab
  await page.evaluate(() => {
    const tab = document.querySelector('.navtab[data-pane="petition"]');
    if (tab) tab.click();
  });
  await sleep(800);

  // Show stat strip
  await screenshot(page, 3);

  // Scroll to verifier arithmetic
  await page.evaluate(() => {
    const pv = document.getElementById('petVerify');
    if (pv) pv.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  await sleep(500);
  await screenshot(page, 7);

  // ── Petition + closing stats — "One knowledge base..." ──
  console.log('6/6  Petition + closing...');
  await page.evaluate(() => {
    const pw = document.getElementById('petitionWrap');
    if (pw) pw.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  await sleep(500);
  await screenshot(page, 4);

  // End on stat strip
  await page.evaluate(() => {
    const ss = document.getElementById('statstrip');
    if (ss) ss.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await sleep(500);
  await screenshot(page, 6);

  await browser.close();
  console.log(`\nCaptured ${frameNum} frames.`);

  // ── Stitch with ffmpeg ──
  console.log('Stitching video with ffmpeg...');
  // Get audio duration so we can pad the last frame to match
  const probeDur = execSync(`ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 ${VOICEOVER}`).toString().trim();
  const audioDur = parseFloat(probeDur);
  const videoDur = frameNum / FPS;
  const pad = Math.max(0, Math.ceil(audioDur - videoDur));
  if (pad > 0) {
    console.log(`Padding last frame for ${pad}s to match audio...`);
    const lastFrame = path.join(FRAMES_DIR, `frame_${String(frameNum - 1).padStart(5, '0')}.png`);
    for (let i = 0; i < pad * FPS; i++) {
      fs.copyFileSync(lastFrame, framePath());
    }
    console.log(`Total frames now: ${frameNum}`);
  }

  const cmd = [
    'ffmpeg', '-y',
    '-framerate', String(FPS),
    '-i', path.join(FRAMES_DIR, 'frame_%05d.png'),
    '-i', VOICEOVER,
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k',
    '-shortest',
    '-movflags', '+faststart',
    OUTPUT
  ].join(' ');

  execSync(cmd, { stdio: 'inherit' });
  console.log(`\nDone! Video saved to: ${OUTPUT}`);
}

main().catch(e => { console.error(e); process.exit(1); });
