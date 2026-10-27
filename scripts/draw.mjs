#!/usr/bin/env node
// Copyright (c) 2026 bosen12. SPDX-License-Identifier: GPL-3.0-only
// Adapted from bosen12's danbooru-draw helper; uses the live project engine.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const out = value => process.stdout.write(JSON.stringify(value, null, 2) + '\n');
const normalize = tag => tag.trim().replaceAll('_', ' ');
const sections = ['subject', 'feature', 'pose', 'clothing', 'env'];
const defaultCounts = { subject: 2, feature: 5, pose: 4, clothing: 3, env: 4 };

function projectRoot() {
  const explicit = process.env.DTR_ROOT || process.env.MOCHI_ROOT;
  const valid = path => existsSync(join(path, 'web', 'engine.js')) && existsSync(join(path, 'web', 'lexicon.json'));
  if (explicit) {
    if (!valid(explicit)) throw Error(`找不到抽牌引擎：${explicit}；DTR_ROOT 應指向排字匣或 Mochi repo`);
    return resolve(explicit);
  }
  for (const start of [process.cwd(), dirname(fileURLToPath(import.meta.url))]) {
    for (let path = resolve(start); ; path = dirname(path)) {
      if (valid(path)) return path;
      if (dirname(path) === path) break;
    }
  }
  throw Error('找不到 web/engine.js 和 web/lexicon.json；請設 DTR_ROOT 指向排字匣或 Mochi repo');
}

function readSpec(args) {
  const at = args.indexOf('--spec');
  const source = at >= 0 ? args[at + 1] : '-';
  if (!source) throw Error('--spec 後面需要檔案名稱或 -');
  const spec = JSON.parse(readFileSync(source === '-' ? 0 : source, 'utf8').replace(/^\uFEFF/, ''));
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw Error('規格必須是 object');
  for (const key of ['pins', 'bans', 'extra', 'heats', 'eras', 'offGroups', 'characterFavorites']) {
    if (spec[key] !== undefined && (!Array.isArray(spec[key]) || spec[key].some(v => typeof v !== 'string')))
      throw Error(`${key} 必須是字串陣列`);
  }
  for (const key of ['counts', 'focus', 'mustDraw']) {
    if (spec[key] !== undefined && (!spec[key] || typeof spec[key] !== 'object' || Array.isArray(spec[key])))
      throw Error(`${key} 必須是 object`);
  }
  if (spec.n !== undefined && (!Number.isInteger(spec.n) || spec.n < 1 || spec.n > 10)) throw Error('n 必須是 1–10 的整數');
  const seed = spec.drawSeed ?? spec.seed;
  if (seed !== undefined && (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff))
    throw Error('drawSeed 必須是 0–4294967295 的整數');
  return spec;
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (!['search', 'groups', 'draw'].includes(command)) {
    throw Error('用法：node draw.mjs search 關鍵字… [--section env] | groups | draw --spec 檔案或-');
  }
  const root = projectRoot();
  const E = await import(pathToFileURL(join(root, 'web', 'engine.js')).href);
  const data = JSON.parse(readFileSync(join(root, 'web', 'lexicon.json'), 'utf8'));
  const lex = E.indexLexicon(data);
  const items = lex.items || data.tags;
  if (command === 'groups') {
    const groups = {};
    for (const item of items) {
      if (!sections.includes(item.section)) continue;
      const group = groups[item.section] ||= {};
      group[item.group] = (group[item.group] || 0) + 1;
    }
    out({ ok: true, root, defaultCounts, skeleton: E.SKELETON, groups,
      heats: E.HEATS, ratings: E.RATINGS, eras: E.ERAS, sceneModes: E.SCENE_MODES });
    return;
  }
  if (command === 'search') {
    let section;
    const words = [];
    for (let i = 0; i < args.length; i++) {
      if (args[i] === '--section') {
        section = args[++i];
        if (!sections.includes(section)) throw Error('--section 應為 ' + sections.join('/'));
      } else words.push(args[i]);
    }
    if (!words.length) throw Error('search 需要至少一個關鍵字');
    const results = {};
    for (const word of words) {
      const q = normalize(word).toLowerCase();
      const scored = [];
      for (const it of items) {
        if (section && it.section !== section) continue;
        const tag = it.tag.toLowerCase(), zh = String(it.zh || data.zh?.[it.tag] || '');
        let score = -1;
        if (tag === q || zh === word) score = 0;
        else if (tag.startsWith(q) || zh.startsWith(word)) score = 1;
        else if (tag.split(/[\s()]+/).includes(q)) score = 2;
        else if (zh.includes(word)) score = 3;
        else if (tag.includes(q)) score = 4;
        if (score >= 0) scored.push({ score, it, zh });
      }
      scored.sort((a, b) => a.score - b.score || a.it.tag.length - b.it.tag.length);
      results[word] = scored.slice(0, 12).map(({ it, zh }) => ({
        tag: it.tag, zh, section: it.section, group: it.group, heat: it.heat, era: it.era,
      }));
    }
    out({ ok: true, results });
    return;
  }

  const spec = readSpec(args);
  for (const [key, allowed] of [['heats', E.HEATS], ['eras', E.ERAS], ['rating', E.RATINGS], ['sceneMode', E.SCENE_MODES]]) {
    if (spec[key] === undefined) continue;
    const values = Array.isArray(spec[key]) ? spec[key] : [spec[key]];
    if (!values.length || values.some(value => !allowed.includes(value))) throw Error(`${key} 含未知值或空清單`);
  }
  const pins = [...new Set((spec.pins || []).map(normalize))];
  const bans = [...new Set((spec.bans || []).map(normalize))];
  const notInLexicon = pins.filter(tag => !lex.byTag.has(tag));
  // Unknown bans cannot reliably be applied by the engine; report instead of silently accepting.
  const unknownBans = bans.filter(tag => !lex.byTag.has(tag));
  const extras = [...new Set([...(spec.extra || []).map(normalize), ...notInLexicon])];
  let settings = E.sanitizeSettings({ ...spec, rating: spec.rating ?? 'general',
    heats: spec.heats ?? ['activity'], eras: spec.eras ?? ['modern'],
    counts: { ...defaultCounts, ...spec.counts } }, data);
  const off = [...(spec.offGroups || [])];
  for (const [section, list] of Object.entries(E.SKELETON)) {
    const n = Number(settings.counts[section]);
    if (!(n > 0 && n < E.skeletonCap(section))) continue;
    const requested = spec.focus?.[section];
    if (requested !== undefined && (!Array.isArray(requested) || requested.some(v => typeof v !== 'string')))
      throw Error(`focus.${section} 必須是字串陣列`);
    if (!requested?.length) {
      off.push(...E.stepSkeleton(settings, section, n).offGroups.filter(k => k.startsWith(section + ':')));
    } else {
      const keys = list.map(([key]) => key);
      const unknown = requested.filter(key => !keys.includes(key));
      if (unknown.length) throw Error(`focus.${section} 未知分類：${unknown.join(', ')}`);
      const lit = [...new Set([...requested, ...keys])].slice(0, n);
      off.push(...keys.filter(key => !lit.includes(key)).map(key => section + ':' + key));
    }
  }
  settings = { ...settings, offGroups: E.sanitizeOffGroups(off) };
  let pinned = new Set(), banned = new Set();
  for (const tag of pins.filter(tag => lex.byTag.has(tag))) {
    ({ pinned, userBanned: banned } = E.applyPin(lex, pinned, banned, tag,
      { keepMutex: settings.pinMutex === false, eraMix: settings.eraMix }));
  }
  for (const tag of bans) ({ pinned, userBanned: banned } = E.applyBan(lex, pinned, banned, tag));
  const tail = new Set([...(data.quality || []), ...(data.nsfwTail || []), ...(data.sfwTail || []), ...(data.sensitiveTail || [])]);
  const results = [];
  for (let i = 0; i < (spec.n ?? 1); i++) {
    const seed = (spec.drawSeed ?? spec.seed) === undefined ? E.randomSeed() : ((spec.drawSeed ?? spec.seed) + i) >>> 0;
    const r = E.drawOne(lex, settings, pinned, banned, E.mulberry32(seed), seed);
    const tags = r.positive.split(',').map(t => t.trim()).filter(Boolean);
    const wanted = [...new Set([...(r.people > 0 ? ['adult'] : []), ...extras])].filter(t => !tags.includes(t) && !bans.includes(t));
    const subjects = new Set(r.sections?.subject || []);
    let at = 0;
    while (at < tags.length && subjects.has(tags[at])) at++;
    if (wanted.includes('adult')) tags.splice(at, 0, 'adult');
    const tailIndex = tags.findIndex(t => tail.has(t));
    tags.splice(tailIndex < 0 ? tags.length : tailIndex, 0, ...wanted.filter(t => t !== 'adult'));
    results.push({ seed, positive: [...new Set(tags)].join(', '), tagCount: new Set(tags).size,
      heat: r.heat, era: r.era, people: r.people, sections: r.sections,
      droppedPins: pins.filter(t => !tags.includes(t)), conflicts: r.conflicts,
      eraClash: r.eraClash, heatClash: r.heatClash });
  }
  out({ ok: true, root, settings, pinned: [...pinned], banned: [...banned], notInLexicon, unknownBans, results });
}

try { await main(); }
catch (error) { out({ ok: false, error: error.message }); process.exitCode = 1; }
