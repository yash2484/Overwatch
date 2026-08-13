import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

// Merge the Vite config so the React + Tailwind plugins transform any TSX test files and
// the dev proxy stays out of the way. A bare standalone config would silently fail to
// transform JSX the moment a component test appears.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  }),
);
