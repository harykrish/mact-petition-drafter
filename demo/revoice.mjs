/**
 * Re-voice demo.mp4 in Hari's own cloned voice (ElevenLabs "Hari (Narrator)").
 * Generates sentence-by-sentence (eleven_v3) with prosody continuity + small
 * pauses for a natural delivery, re-times the existing captured frames to the
 * new audio, and rebuilds the video in sync.
 *
 * Run from the demo/ dir:  node revoice.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';

const DIR = path.resolve('.');
const FRAMES = path.join(DIR, 'frames');
const SEQ = path.join(DIR, '_seq');
const AUD = path.join(DIR, '_aud');
const FPS = 30;
const MODEL = 'eleven_v3';
const GAP = 0.16;                                           // pause between sentences (s)
const VOICE = 'KARbTsDfSx28zw8lCcga';                       // Hari (Narrator)
const KEY = fs.readFileSync('/Users/harikrishna/dev/tap_to_talk/appa-app/.env', 'utf8')
  .match(/ELEVENLABS_API_KEY=(.+)/)[1].trim().replace(/['"]/g, '');

const sh = (c) => execSync(c, { stdio: ['ignore', 'pipe', 'inherit'] }).toString();
const dur = (f) => parseFloat(sh(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${f}"`).trim());

// narration grouped to the actual capture sections (frame ranges, inclusive).
// "Nyaaya Saytoo" = phonetic respelling of NyayaSetu so the TTS says it right.
const sections = [
  { name: 'intro',    a: 0,   b: 119, text: "A catastrophic road accident doesn't just create a legal problem. It creates a medical crisis, a financial crisis, and a communication crisis — all at once. The family is buried in hospital records, police reports, insurance papers. Over a million of these cases are stuck in Indian tribunals right now. Ten billion dollars unpaid. Cambrian builds a living knowledge base from all of it. Every fact sourced, every conflict flagged, every update tracked. From that one knowledge base, multiple agents act — legal drafting, medical advocacy, rehab planning, even communication for patients who've lost the ability to speak. Today, we're showing Nyaaya Saytoo, the legal agent. Watch." },
  { name: 'ingest',   a: 120, b: 179, text: "Nine documents go in. Claude extracts structured facts, and a reconciler catches conflicts across sources." },
  { name: 'contra',   a: 180, b: 203, text: "The police report says March fifth, the hospital says March sixth — that contradiction gets flagged, never buried." },
  { name: 'kbverify', a: 204, b: 223, text: "An independent verifier — fresh context, no memory of the extraction — audits the knowledge base against ten invariants. Only when every check passes does the system commit." },
  { name: 'draft',    a: 224, b: 295, text: "Claude drafts the petition. A second independent agent re-derives every figure from scratch. Over a million dollars in lost earnings. If a single number is wrong, it rejects and loops back — autonomously." },
  { name: 'close',    a: 296, b: 351, text: "One knowledge base. Twelve orchestrated Claude calls. Two independent verification agents. From weeks to minutes." },
];

fs.rmSync(SEQ, { recursive: true, force: true }); fs.mkdirSync(SEQ, { recursive: true });
fs.rmSync(AUD, { recursive: true, force: true }); fs.mkdirSync(AUD, { recursive: true });

// shared silence clip for inter-sentence pauses
const SIL = path.join(AUD, 'sil.wav');
sh(`ffmpeg -y -loglevel error -f lavfi -i anullsrc=r=44100:cl=stereo -t ${GAP} "${SIL}"`);

// flatten to sentences (keep section index) for continuity context
const sents = [];
sections.forEach((s, si) => {
  s.text.split(/(?<=[.!?—])\s+/).map((t) => t.trim()).filter(Boolean).forEach((t) => sents.push({ si, text: t }));
});

// ---- 1. generate each sentence in Hari's voice ----
for (let i = 0; i < sents.length; i++) {
  const body = {
    text: sents[i].text,
    model_id: MODEL,
    voice_settings: { stability: 0.5, similarity_boost: 0.9, style: 0.0, use_speaker_boost: true },
  };
  process.stdout.write(`tts ${i + 1}/${sents.length} … `);
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${VOICE}`, {
    method: 'POST', headers: { 'xi-api-key': KEY, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`TTS ${i} failed ${res.status}: ${await res.text()}`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length < 800) throw new Error(`TTS ${i} too small: ${buf.length}`);
  const mp3 = path.join(AUD, `s${i}.mp3`), wav = path.join(AUD, `s${i}.wav`);
  fs.writeFileSync(mp3, buf);
  sh(`ffmpeg -y -loglevel error -i "${mp3}" -ar 44100 -ac 2 "${wav}"`);
  sents[i].wav = wav;
  console.log('ok');
}

// ---- 2. build per-section audio (sentences + pauses) and measure ----
for (let si = 0; si < sections.length; si++) {
  const wavs = sents.filter((x) => x.si === si).map((x) => x.wav);
  const list = wavs.flatMap((w) => [`file '${w}'`, `file '${SIL}'`]).join('\n');
  const lf = path.join(AUD, `sec${si}.txt`);
  fs.writeFileSync(lf, list + '\n');
  const sw = path.join(AUD, `sec${si}.wav`);
  sh(`ffmpeg -y -loglevel error -f concat -safe 0 -i "${lf}" -c copy "${sw}"`);
  sections[si].wav = sw;
  sections[si].dur = dur(sw);
  console.log(`${sections[si].name}: ${sections[si].dur.toFixed(2)}s`);
}

// ---- 3. re-time each section's frames to its new audio duration (30fps) ----
let out = 0;
for (const s of sections) {
  const nSrc = s.b - s.a + 1;
  const nOut = Math.round(s.dur * FPS);
  for (let k = 0; k < nOut; k++) {
    const src = s.a + Math.floor((k * nSrc) / nOut);
    fs.copyFileSync(path.join(FRAMES, `frame_${String(src).padStart(5, '0')}.png`), path.join(SEQ, `s${String(out++).padStart(5, '0')}.png`));
  }
}
console.log(`frames: ${out} (${(out / FPS).toFixed(1)}s)`);

// ---- 4. concat section audio → full voiceover, encode + mux ----
fs.writeFileSync(path.join(AUD, 'full.txt'), sections.map((s) => `file '${s.wav}'`).join('\n') + '\n');
sh(`ffmpeg -y -loglevel error -f concat -safe 0 -i "${path.join(AUD, 'full.txt')}" -c copy "${path.join(AUD, 'voiceover.wav')}"`);
fs.copyFileSync(path.join(AUD, 'voiceover.wav'), path.join(DIR, 'voiceover_hari.wav'));

console.log('encoding…');
sh(`ffmpeg -y -loglevel error -framerate ${FPS} -i "${path.join(SEQ, 's%05d.png')}" -i "${path.join(AUD, 'voiceover.wav')}" ` +
   `-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r ${FPS} -c:a aac -b:a 192k -shortest -movflags +faststart "${path.join(DIR, 'demo_hari.mp4')}"`);

fs.rmSync(SEQ, { recursive: true, force: true });
console.log('done → demo/demo_hari.mp4  ' + sh(`ffprobe -v error -show_entries format=duration -of csv=p=0 "${path.join(DIR, 'demo_hari.mp4')}"`).trim() + 's');
