import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/* Build output goes straight into the Flask app's static folder, and the bundle is committed.
 *
 * Why committed rather than built on deploy: the Railway image is a Python image running
 * gunicorn. Adding Node to it means a second toolchain in the release path for a page that
 * changes rarely -- and an unpinned dependency in that path has already taken production down
 * once. `npm run build` here, commit the result, deploy as usual.
 *
 * `base` must match where Flask serves those files. The app is mounted at APP_URL_PREFIX, so the
 * assets live under <prefix>/static/insurance/. Change the prefix and you must rebuild; the
 * value is read from VITE_ASSET_BASE so CI or a different deployment can override it.
 */
const ASSET_BASE = process.env.VITE_ASSET_BASE || '/travel-companions/static/insurance/';

export default defineConfig({
  plugins: [react()],
  base: ASSET_BASE,
  build: {
    outDir: '../../app/static/insurance',
    emptyOutDir: true,
    // Stable names: the Flask template references these directly, so a content hash would mean
    // editing the template on every build.
    rollupOptions: {
      output: {
        entryFileNames: 'travel-insurance.js',
        chunkFileNames: 'travel-insurance-[name].js',
        assetFileNames: (info) =>
          info.name && info.name.endsWith('.css')
            ? 'travel-insurance.css'
            : 'assets/[name][extname]',
      },
    },
  },
});
