import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The approved PRAMA assets remain the source of truth outside the app.
  // Vite copies them verbatim into the production bundle.
  publicDir: "../UI",
});
