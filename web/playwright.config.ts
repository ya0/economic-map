import { defineConfig } from "@playwright/test";

const port = process.env.E2E_PORT ?? "4199", url = `http://localhost:${port}`;

/** WebGL on the GPU (Direct3D on Windows): the terrain tests take seconds there and minutes under software GL (`E2E_ANGLE=swiftshader`),
 * which gets twice the time. */
const angle = process.env.E2E_ANGLE ?? (process.platform === "win32" ? "d3d11" : "swiftshader");

/** The smoke test builds into its own directory and port, so it never rewrites or reuses dist, which may be served live. */
export default defineConfig({
  testDir: "e2e",
  timeout: angle === "swiftshader" ? 180_000 : 90_000,
  expect: { timeout: 15_000 },
  use: { baseURL: url, reducedMotion: "reduce", colorScheme: "dark", launchOptions: { executablePath: process.env.E2E_CHROMIUM || undefined, args: ["--use-gl=angle", `--use-angle=${angle}`, "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] } },
  webServer: { command: `npx vite build --outDir dist-e2e && npx vite preview --outDir dist-e2e --port ${port} --strictPort`, url, timeout: 120_000 },
});
