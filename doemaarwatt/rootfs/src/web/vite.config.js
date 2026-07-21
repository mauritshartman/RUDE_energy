import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: false
        // // Split luxon into its own chunk. luxon is needed eagerly (home view +
        // // the control store), while chart.js is only used by the async graph
        // // components. Left alone, Rollup bundles the two together, so the eager
        // // luxon import drags chart.js onto every page. Isolating luxon lets
        // // Rollup keep chart.js in an async-only chunk that loads only when a
        // // graph actually mounts.
        // manualChunks(id) {
        //   if (id.includes('node_modules/luxon')) {
        //     return 'luxon'
        //   }
        // },
      },
    },
  },
})
