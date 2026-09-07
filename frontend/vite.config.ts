import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Static application assets are kept inside this service so the Railway
  // frontend build remains self-contained when its root directory is /frontend.
  publicDir: "public",
});
