// Base URL for all backend API calls.
//
// Vite sets `import.meta.env.DEV` to true under `npm run dev`, where we talk to the
// backend directly on localhost.
//
// In a production build the frontend is served by the add-on's aiohttp server, which
// may sit behind Home Assistant's ingress proxy. Ingress prefixes every request path
// with a per-session token (e.g. /api/hassio_ingress/<token>) that is unknown at build
// time, so a fixed '/api' would bypass the prefix and 404. We instead derive the prefix
// at runtime from this module's own URL: the bundle is loaded from
// `<ingress-prefix>/assets/<chunk>.js` (the add-on rewrites the entry <script> tag to
// the ingress path, and every chunk loads relative to it), so stripping `/assets/...`
// off `import.meta.url` yields the prefix. Direct (non-ingress) access has no prefix, so
// the result is just '/api'.
//
// Optionally override with a `VITE_API_BASE` entry in a `.env` / `.env.local` file
// (e.g. to point the dev frontend at a backend on another host).
function ingressApiBase() {
    try {
        const { pathname } = new URL(import.meta.url)
        const i = pathname.lastIndexOf('/assets/')
        return `${i >= 0 ? pathname.slice(0, i) : ''}/api`
    } catch {
        return '/api'
    }
}

console.log(`API.js pathname: '${new URL(import.meta.url)}'`)


export const API_BASE =
    import.meta.env.VITE_API_BASE ??
    (import.meta.env.DEV ? 'http://localhost:8099/api' : ingressApiBase())
