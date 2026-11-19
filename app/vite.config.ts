/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { VitePWA } from 'vite-plugin-pwa';

// GitHub Pages serves the app from /<repo>/; the workflow sets BASE_PATH.
const base = process.env.BASE_PATH || '/';

export default defineConfig({
  base,
  define: {
    'import.meta.env.VITE_REPO': JSON.stringify(process.env.VITE_REPO || process.env.GITHUB_REPOSITORY || ''),
  },
  plugins: [
    preact(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/*.png', 'icons/*.svg'],
      manifest: {
        name: 'Specials Tracker',
        short_name: 'Specials',
        description: 'Stand-up comedy specials: what is new, what you want to see, and a random pick.',
        theme_color: '#14110f',
        background_color: '#14110f',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '.',
        scope: '.',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // The database is fetched by the app itself and kept in IndexedDB,
        // so the service worker only precaches the app shell.
        globPatterns: ['**/*.{js,css,html,png,svg,webmanifest}'],
        globIgnores: ['data/**'],
        navigateFallback: 'index.html',
      },
    }),
  ],
  test: {
    environment: 'node',
  },
});
