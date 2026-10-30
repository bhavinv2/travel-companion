import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/* Draft of the NRI Parent Service homepage, rebuilt in React from nri-parent-service-homepage.html.
 *
 * Same arrangement as frontend/sahayak: the build goes straight into the Flask app's static
 * folder and is committed, so the Python image never needs Node. `npm run build` here, commit
 * the result, deploy as usual. Served by routes/homepage_draft.py at /homepage-draft.
 *
 * `base` is './' so images resolve against the bundle's own URL and the same build works with
 * or without the /travel-companions prefix.
 */
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../../app/static/homepage-draft',
    emptyOutDir: true,
    // Stable names: the Flask template references these directly. Images keep their hash.
    rollupOptions: {
      output: {
        entryFileNames: 'homepage-draft.js',
        chunkFileNames: 'homepage-draft-[name].js',
        assetFileNames: (info) =>
          info.name && info.name.endsWith('.css') ? 'homepage-draft.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
