#!/usr/bin/env node
/**
 * Codegen pipeline for backend TypeScript types.
 *
 * Two-step canonical derivation:
 *   1. `python scripts/dump_openapi_schema.py` → backend-schema.json
 *      (schema derived from FastAPI app, which derives from Pydantic models —
 *       single source of truth; the static tools/gimo_server/openapi.yaml is
 *       documentation-oriented and may drift)
 *   2. `openapi-typescript` → backend-generated.ts
 *
 * Flags:
 *   (none)    — regenerate the TS file
 *   --check   — regenerate into a temp dir and diff against committed output.
 *               Fail with exit code 1 if they differ (CI drift guard).
 *
 * This script enforces the invariant from AGENTS.md:
 *   "UI must not invent backend truth"
 * Regression guard for audit findings F3, F4, F5 (TypeScript contract drift).
 */
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

const __filename = fileURLToPath(import.meta.url);
const UI_ROOT = resolve(dirname(__filename), "..");
const REPO_ROOT = resolve(UI_ROOT, "..", "..");

const CHECK_MODE = process.argv.includes("--check");

const SCHEMA_JSON = join(UI_ROOT, "src", "types", "backend-schema.json");
const GENERATED_TS = join(UI_ROOT, "src", "types", "backend-generated.ts");

function run(cmd, opts = {}) {
    execSync(cmd, { stdio: "inherit", cwd: REPO_ROOT, ...opts });
}

function pickPython() {
    // Honor explicit override first, then repo venvs, then PATH.
    if (process.env.PYTHON) return process.env.PYTHON;
    const candidates = [
        join(REPO_ROOT, ".venv", "Scripts", "python.exe"),
        join(REPO_ROOT, ".venv", "bin", "python"),
        join(REPO_ROOT, "venv", "Scripts", "python.exe"),
        join(REPO_ROOT, "venv", "bin", "python"),
    ];
    for (const c of candidates) {
        if (existsSync(c)) return c;
    }
    return process.platform === "win32" ? "python" : "python3";
}

function step1DumpSchema() {
    const py = pickPython();
    console.log(`[codegen] Step 1/2 — dumping OpenAPI schema via ${py}`);
    run(`"${py}" scripts/dump_openapi_schema.py`);
}

function step2GenerateTs(outputPath) {
    console.log(`[codegen] Step 2/2 — generating TS → ${outputPath}`);
    run(`npx --no-install openapi-typescript "${SCHEMA_JSON}" -o "${outputPath}"`, { cwd: UI_ROOT });
}

function normalize(text) {
    // Strip trailing whitespace + normalize line endings for cross-platform diff stability.
    return text.replace(/\r\n/g, "\n").replace(/[ \t]+$/gm, "");
}

async function main() {
    step1DumpSchema();

    if (!CHECK_MODE) {
        step2GenerateTs(GENERATED_TS);
        console.log("[codegen] Done. Regenerated types committed at:");
        console.log(`  ${GENERATED_TS}`);
        return;
    }

    // Drift check: generate into temp, diff against committed.
    const tmp = mkdtempSync(join(tmpdir(), "gimo-codegen-check-"));
    const tmpOut = join(tmp, "backend-generated.ts");
    try {
        step2GenerateTs(tmpOut);
        const fresh = normalize(readFileSync(tmpOut, "utf8"));
        if (!existsSync(GENERATED_TS)) {
            console.error(`[codegen:check] FAIL — ${GENERATED_TS} does not exist. Run \`npm run codegen\`.`);
            process.exit(1);
        }
        const committed = normalize(readFileSync(GENERATED_TS, "utf8"));
        if (fresh !== committed) {
            console.error("[codegen:check] FAIL — backend-generated.ts is out of sync with the live OpenAPI schema.");
            console.error("  Run `npm run codegen` and commit the result.");
            process.exit(1);
        }
        console.log("[codegen:check] OK — types are in sync with backend schema.");
    } finally {
        rmSync(tmp, { recursive: true, force: true });
    }
}

main().catch((err) => {
    console.error(err);
    process.exit(1);
});
