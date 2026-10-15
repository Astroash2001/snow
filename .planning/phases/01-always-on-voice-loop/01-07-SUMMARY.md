---
phase: 01-always-on-voice-loop
plan: 07
subsystem: ui
tags: [electron, electron-vite, typescript, biome, vitest, ajv, json-schema-to-typescript, contracts]

requires:
  - phase: 01-04
    provides: contracts/events.schema.json and golden samples (events.json, conversation-12.jsonl)
provides:
  - hud/ project with exact pins, committed package-lock.json and npm scripts (dev, build, start, test, e2e, lint, typecheck, gen:types)
  - hud/src/generated/contracts.d.ts generated from the hub JSON Schema
  - ajv contract test proving every golden sample is valid against the schema
affects: [01-09, 01-10, 01-11, 01-12, 01-13, 01-14]

commits: 1
plan_head_before: f12b47dbece29993c5b9eeb1f0afbf9a2c67c229
plan_head_after: baf1d538bdb2c3f3f6a1faf77a26d69162332487

actuals:
  tokens: 28000
  tasks: 1
  commits: 1

tech-stack:
  added: [electron 44.7.2, electron-vite 6.0.0, vite 8.3.4, react 19.3.1, zustand 5.0.15, tailwindcss 4.3.3, typescript 7.0.2, vitest 5.0.4, "@playwright/test 1.64.1", "@biomejs/biome 2.5.15", json-schema-to-typescript 16.0.0, ajv 8.20.0, ws 8.22.0, lucide-react 1.57.0, fontsource inter and jetbrains-mono]
  patterns:
    - "Wire types are generated from the Python-exported schema, never hand-written; regenerate leaves git diff clean"
    - "Contract tests import schema and samples via Vite JSON and ?raw imports, so no Node typings are needed"

key-files:
  created:
    - hud/package.json
    - hud/package-lock.json
    - hud/tsconfig.json
    - hud/biome.json
    - hud/vitest.config.ts
    - hud/.gitignore
    - hud/.gitattributes
    - hud/src/generated/contracts.d.ts
    - hud/src/renderer/src/contracts.test.ts
  modified: []

key-decisions:
  - "json-schema-to-typescript 16 renders the Pydantic oneOf+discriminator unions correctly (assumption A10 holds); no quicktype fallback needed"
  - "TypeScript 7.0.2 works with Biome, Vitest and json2ts here; no 6.x fallback"
  - "ajv 8.20.0 and ws 8.22.0 chosen as the newest 8.x at least 14 days old (ws 8.22.0 is 20 days old, 8.22.x newer ones excluded by the age rule)"
  - "type: module deliberately not set; electron-vite output format is left for plan 01-09 to decide with the window code"

patterns-established:
  - "Generated root type is EventsSchema (the schema has no root title); the test aliases it as WireMessage"

requirements-completed: [CORE-03, HUD-03]

coverage:
  - id: D1
    description: "HUD project pinned exactly with lockfile, lint, type check and unit test scripts"
    requirement: "CORE-03"
    verification:
      - kind: integration
        ref: "npm --prefix hud run lint; npm --prefix hud run typecheck; npm --prefix hud run test"
        status: pass
    human_judgment: false
  - id: D2
    description: "TypeScript contract types generated from contracts/events.schema.json, regeneration leaves git diff clean"
    requirement: "CORE-03"
    verification:
      - kind: integration
        ref: "npm --prefix hud run gen:types && git diff --exit-code hud/src/generated"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every golden sample (events.json and all 116 conversation-12.jsonl lines) validates against the schema with ajv"
    requirement: "HUD-03"
    verification:
      - kind: unit
        ref: "hud/src/renderer/src/contracts.test.ts (154 tests)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-10-16
status: complete
---

# Phase 1 Plan 07: HUD Toolchain and Generated Contract Types Summary

**The `hud/` Electron project exists with exact pins and a committed lockfile, and its TypeScript wire types are generated from the hub's JSON Schema and checked sample-for-sample (154 ajv tests) against the Python golden fixtures**

## Accomplishments
- `npm run gen:types` produces `hud/src/generated/contracts.d.ts` (1028 lines, all 28 event types, commands and Snapshot); the discriminated unions come out as clean TypeScript unions.
- `contracts.test.ts` compiles the schema with ajv (draft 2020, `strict: false`), validates every `events.json` entry and all 116 `conversation-12.jsonl` lines, rejects an unknown frame kind, and type-checks a sample against the generated union.
- `lint` (Biome 2.5.15, clean), `typecheck` (tsc 7.0.2, clean), `test` (Vitest 5.0.4, 154 pass) all run from npm scripts.
- `"main": "./out/main/index.js"` is set for the hub's `electron.exe hud` worker entry (plan 01-09 adds the code that produces it).
- `npm audit --omit=dev`: found 0 vulnerabilities.

## Task Commits
1. **Task 1 (tracer): HUD toolchain and contract types** - `baf1d53` (feat)

Tracer gate: `<verify>` re-run end to end (test, typecheck, lint all exit 0), tracer verified, expansion unblocked.

## Deviations from Plan

### Auto-fixed / additive

**1. [Rule 3 - Blocker] First install needed `--legacy-peer-deps`**
- **Found during:** Task 1
- **Issue:** `npm install` (npm 11.3.0) crashed in arborist `#loadPeerSet` with `Cannot read properties of null (reading 'edgesOut')` while resolving vitest 5.0.4's optional peers. No package was added or changed.
- **Fix:** one `npm install --legacy-peer-deps` generated the lockfile; `npm ci` then installs from it with no flag (verified). No `.npmrc` was added.
- **Files modified:** hud/package-lock.json
- **Commit:** baf1d53

**2. [Plan-directed] `hud/.gitignore` instead of editing the root .gitignore** (node_modules/, out/, test-results/, playwright-report/), per orchestrator instruction.

**3. [Rule 2 - Missing critical] `hud/.gitattributes` (`* text=auto eol=lf`)**
- **Issue:** the user's git has autocrlf on (commit warned LF to CRLF); Biome's formatter requires LF, so `biome ci` and the generated-types diff gate would fail on a Windows checkout.
- **Fix:** pin LF for everything under `hud/`.

**4. [Rule 3 - Blocker] tsconfig uses `types: ["vite/client"]` instead of `@types/node`**: the test reads JSON and `.jsonl` through Vite imports (`?raw`), so no Node typings are required and no undeclared transitive package is relied on.

**5. biome.json omits `"recommended": true`**: recommended rules are on by default and the field is deprecated in Biome 2.5 (it produced a diagnostic).

**Total deviations:** 5 (1 blocker workaround, 1 plan-directed, 1 missing-critical, 2 config choices). **Impact:** none on scope; no packages beyond the plan's list.

## Issues Encountered
- The generated root type is named `EventsSchema` (the exported schema has no root title), not `WireMessage`. The test aliases `type WireMessage = EventsSchema`. A later plan can either add a root `title` in `snow.contracts.export` or re-export the alias from a hand-written module.
- Vitest prints a non-fatal warning that `vitest.config.ts` is ESM loaded as CJS (no `"type": "module"`). Left as is on purpose (see key-decisions); `vitest.config.mts` or `type: module` resolves it when 01-09 settles the electron-vite output format.
- Vitest 5.0.4 reports `EBADENGINE` on Node 25.6.0 (wants ^22.12 || ^24 || >=26). Only a warning; tests run. CI should use an LTS Node (plan 01-10).

## Known Stubs
None.

## Threat Flags
None. T-01-56 and T-01-SC mitigations in place locally: types generated from the committed schema, golden samples ajv-validated, exact pins plus lockfile, audit clean. The CI regenerate-and-diff and `npm ci` steps land in plan 01-10.

## Self-Check: PASSED
- hud/package.json, package-lock.json, tsconfig.json, biome.json, vitest.config.ts, src/generated/contracts.d.ts, src/renderer/src/contracts.test.ts: all present
- commit baf1d53 present on branch
- acceptance: `"main": "./out/main/index.js"`, `"electron": "44.7.2"`, `gen:types` present; generated file contains `transcript.final`; `gen:types` leaves `git diff --exit-code hud/src/generated` clean; contracts.test.ts passes
