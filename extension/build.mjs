#!/usr/bin/env node
/**
 * build.mjs — esbuild bundler for the Reel Inbox Scraper extension.
 *
 * Usage:
 *   node build.mjs [--target=chrome|firefox|all] [--watch]
 *
 * Outputs dist-chrome/ and/or dist-firefox/.
 */

import * as esbuild from "esbuild";
import { readFileSync, writeFileSync, cpSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { rimraf } from "rimraf";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ── CLI flag parsing ─────────────────────────────────────────────────────────

const args = process.argv.slice(2);
const targetFlag = args.find((a) => a.startsWith("--target="))?.split("=")[1] ?? "all";
const isWatch = args.includes("--watch");

const VALID_TARGETS = ["chrome", "firefox", "all"];
if (!VALID_TARGETS.includes(targetFlag)) {
  console.error(`Invalid --target="${targetFlag}". Use: chrome | firefox | all`);
  process.exit(1);
}

const targets = targetFlag === "all" ? ["chrome", "firefox"] : [targetFlag];

// ── Manifest construction ─────────────────────────────────────────────────────

const base = JSON.parse(readFileSync(resolve(__dirname, "manifest.base.json"), "utf-8"));

function buildManifest(target) {
  const manifest = { ...base };

  if (target === "chrome") {
    manifest.background = {
      service_worker: "background.js",
      type: "module",
    };
  } else if (target === "firefox") {
    manifest.background = {
      scripts: ["background.js"],
      type: "module",
    };
    manifest.browser_specific_settings = {
      gecko: {
        id: "reel-inbox@local",
        strict_min_version: "121.0",
      },
    };
  }

  return manifest;
}

// ── Static file copy ──────────────────────────────────────────────────────────

function copyStatics(outDir) {
  // popup.html, options.html
  for (const file of ["popup.html", "options.html"]) {
    const src = resolve(__dirname, "src", file);
    const dest = resolve(outDir, file);
    cpSync(src, dest);
  }

  // icons/
  const iconsDir = resolve(__dirname, "icons");
  const destIconsDir = resolve(outDir, "icons");
  if (existsSync(iconsDir)) {
    mkdirSync(destIconsDir, { recursive: true });
    cpSync(iconsDir, destIconsDir, { recursive: true });
  }
}

// ── esbuild entry points ──────────────────────────────────────────────────────

const entryPoints = [
  resolve(__dirname, "src/content.ts"),
  resolve(__dirname, "src/background.ts"),
  resolve(__dirname, "src/popup.ts"),
  resolve(__dirname, "src/options.ts"),
];

// ── Build function ─────────────────────────────────────────────────────────────

async function buildTarget(target) {
  const outDir = resolve(__dirname, `dist-${target}`);

  // Clean
  await rimraf(outDir);
  mkdirSync(outDir, { recursive: true });

  // esbuild
  const ctx = await esbuild.context({
    entryPoints,
    outdir: outDir,
    bundle: true,
    format: "esm",
    target: "es2022",
    sourcemap: true,
    platform: "browser",
    // No external — zero runtime deps
    logLevel: "info",
  });

  if (isWatch) {
    await ctx.watch();
    console.log(`[${target}] Watching for changes…`);
  } else {
    await ctx.rebuild();
    await ctx.dispose();
  }

  // Copy statics
  copyStatics(outDir);

  // Write manifest
  const manifest = buildManifest(target);
  writeFileSync(
    resolve(outDir, "manifest.json"),
    JSON.stringify(manifest, null, 2),
    "utf-8"
  );

  console.log(`[${target}] Built → ${outDir}`);
}

// ── Run ───────────────────────────────────────────────────────────────────────

console.log(`Building target(s): ${targets.join(", ")}${isWatch ? " (watch mode)" : ""}`);

for (const target of targets) {
  await buildTarget(target);
}

if (!isWatch) {
  console.log("Build complete.");
}
