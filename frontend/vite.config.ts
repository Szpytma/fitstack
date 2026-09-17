import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    // Bind every interface so other devices on the LAN can reach the app.
    // Without this Vite listens on ::1 only — IPv6 loopback, this machine only.
    //
    // SECURITY: FitStack has no authentication. Anyone who can reach this port
    // can read your health history, see the GPS traces that start at your home,
    // and write to your Garmin account. Keep it to a network you trust and
    // never port-forward it.
    host: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
