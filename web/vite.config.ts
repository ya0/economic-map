import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";

/** Build only: drop the flag SVGs of countries that indicators.json does not hold (the glob in flags.ts matches all of flag-icons). */
const usedFlagsOnly = {
  name: "used-flags-only",
  generateBundle(_: unknown, bundle: Record<string, unknown>) {
    const { meta, regions } = JSON.parse(readFileSync(new URL("public/indicators.json", import.meta.url), "utf8"));
    const used = new Set(Object.values<string[]>(regions).map((r) => r[meta.columns.indexOf("iso2")].toLowerCase()));
    for (const file of Object.keys(bundle)) if (/\/..-[^/]*\.svg$/.test(file) && !used.has(file.split("/").pop()!.slice(0, 2))) delete bundle[file];
  },
};

export default defineConfig({
  base: "./",
  build: { chunkSizeWarningLimit: 1200 },
  plugins: [usedFlagsOnly],
  test: { include: ["test/**/*.test.ts"] },
});
