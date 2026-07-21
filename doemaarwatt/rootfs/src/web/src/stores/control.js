import { defineStore } from 'pinia'
import { DateTime } from 'luxon'
import { API_BASE } from './api'

export const useControlStore = defineStore('control', {
    state: () => ({
        running: false,
        running_start: null,
        mode: 1,
        error_status: '',
        stats: null,
        prices: null,
        schedule: null,
        schedule_ts: null,
        update_time: DateTime.now(),
    }),

    getters: {
        // Backend stats shape: { battery_inverters, solar_inverters, energy_meter }.
        // Battery inverters are single-phase, so their `ac_side` is keyed by the
        // connected phase. Flatten each into a row with the phase and its AC data.
        battery_rows: (state) =>
            Object.entries(state.stats?.battery_inverters ?? {}).map(([name, inv]) => {
                const phase = Object.keys(inv.ac_side ?? {})[0] ?? null
                return {
                    name,
                    phase,
                    control_status: inv.control_status,
                    battery: inv.battery,
                    ac: phase ? inv.ac_side[phase] : null,
                }
            }),
        // Solar inverters can span multiple phases; keep the per-phase `ac_side`.
        solar_rows: (state) =>
            Object.entries(state.stats?.solar_inverters ?? {}).map(([name, inv]) => ({ name, ...inv })),
        energy_meter: (state) => state.stats?.energy_meter ?? null,
        mode_name: (state) => {
            if (state.mode === 1) { return 'idle' }
            else if (state.mode === 2) { return 'manual' }
            else if (state.mode === 3) { return 'static schedule' }
            else if (state.mode === 4) { return 'dynamic schedule' }
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

            const resp = await fetch(`${API_BASE}${path}`, options)
            if (!resp.ok) { throw new Error(`response status: ${resp.status}`) }
            const ret = await resp.json()
            return ret
        },
        async fetch_log(d) {
            this.error_status = ''
            const options = {
                method: 'POST',
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(d)
            }
            try {
                const resp = await fetch(`${API_BASE}/log`, options)
                if (!resp.ok) { throw new Error(`response status: ${resp.status}`) }
                const ret = await resp.text()
                return ret
            } catch (err) {
                this.error_status = `config store: error while fetching log: ${err.msg}`
                return ''
            }
        },
        async fetch_status() {
            try {
                const status = await this._make_fetch(`/`)

                this.running = status.running
                this.running_start = status.running_start
                this.mode = status.mode
                this.stats = status.stats
                this.prices = status.prices
                this.schedule = status.schedule ?? null
                this.schedule_ts = status.schedule_ts ?? null
                this.update_time = DateTime.now()
            } catch (err) {
                this.running = false
                this.running_start = null
                this.mode = 1
                this.stats = null
                this.prices = null
                this.schedule = null
                this.schedule_ts = null
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
            console.log(`set_running(${r}): /run POSTed`)

            await new Promise(resolve => setTimeout(resolve, 3000))
            await this.fetch_status()
        }
    }
})