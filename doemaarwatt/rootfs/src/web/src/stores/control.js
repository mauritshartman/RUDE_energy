import { defineStore } from 'pinia'

export const useControlStore = defineStore('control', {
    state: () => ({
        running: false,
        running_start: null,
        mode: 1,
        error_status: '',
        stats: null,
    }),

    getters: {
        active_stats: (state) => {
            if (state.stats?.inverters) { return state.stats }
            else { return null }
        },
        active_inv_control: (state) => {
            if (state.stats?.inv_control) { return state.stats.inv_control }
            else { return null }
        },
    },

    actions: {
        async _make_fetch(path, method = 'GET', post_body = null) {
            this.error_status = ''

            const options = { method: method }
            if (method === 'POST' && post_body !== null) {
                options.headers = { "Content-Type": "application/json" }
                options.body = JSON.stringify(post_body)
            }

            // local development fetch line:
            const resp = await fetch(`http://localhost:8099/api${path}`, options)
            // production build fetch line:
            // const resp = await fetch("/api"+path, options)
            if (!resp.ok) { throw new Error(`response status: ${resp.status}`) }
            const ret = await resp.json()
            return ret
        },
        async fetch_status() {
            try {
                const status = await this._make_fetch(`/`)
                this.running = status.running
                this.running_start = status.running_start
                this.mode = status.mode
                this.stats = status.stats
            } catch (err) {
                this.running = false
                this.running_start = null
                this.mode = 1
                this.stats = null
                this.error_status = `control store: error while fetching status: ${err.msg}`
            }
        },
        async set_running(r) {
            try {
                const resp = await this._make_fetch(`/run`, 'POST', { running: r })
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating general config: ${err.msg}`
            }
            await this.fetch_status()
        }
    }
})