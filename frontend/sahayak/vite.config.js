import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/* Build output goes straight into the Flask app's static folder, and the bundle is committed.
 *
 * Same arrangement as frontend/insurance, and for the same reason: the Railway image is a
 * Python image running gunicorn, so building on deploy would mean a second toolchain in the
 * release path for a page that changes rarely. `npm run build` here, commit the result, deploy
 * as usual.
 *
 * `base` is './' rather than the deployed path. Vite then resolves every image against the
 * bundle's own URL (import.meta.url for JS, the stylesheet's URL for CSS), so the same build
 * works whether the app is mounted at /travel-companions or at the root -- which it is on a
 * developer's machine. A baked-in '/travel-companions/static/sahayak/' 404s every image
 * locally, and would 404 them all again the day the prefix changes.
 */
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../../app/static/sahayak',
    emptyOutDir: true,
    // Stable names: the Flask template references these directly, so a content hash would mean
    // editing the template on every build. Images keep their hash -- nothing names them.
    rollupOptions: {
      output: {
        entryFileNames: 'sahayak.js',
        chunkFileNames: 'sahayak-[name].js',
        assetFileNames: (info) =>
          info.name && info.name.endsWith('.css') ? 'sahayak.css' : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
