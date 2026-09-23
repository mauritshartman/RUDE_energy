
import { defineStore } from 'pinia'
import { API_BASE } from './api'
import { useControlStore } from './control'

export const useConfigStore = defineStore('configuration', {
    state: () => ({
        config: null,
        subsystem_types: null,
        error_status: '',
    }),

    getters: {
        loaded:         (state) => state.config !== null,
        general:        (state) => (state.config === null) ? [] : state.config.general,
        battery_inverters:      (state) => (state.config === null) ? [] : state.config.battery_inverters,
        solar_inverters: (state) => (state.config === null) ? [] : state.config.solar_inverters,
        energy_meter:   (state) => (state.config === null) ? -1 : state.config.energy_meter,
        mode_manual:    (state) => (state.config === null) ? -1 : state.config.mode_manual,
        mode_static:    (state) => (state.config === null) ? [] : state.config.mode_static,
        mode_dynamic:   (state) => (state.config === null) ? -1 : state.config.mode_dynamic,
        timezone:       (state) => state.config?.general?.timezone ?? 'UTC',
        // True while the current time falls inside the configured EV charge window (issue #36), both bounds
        // included. An unset window (either time an empty string) is never active. A saved time carries the
        // offset of the configured timezone, so it marks a single instant whatever timezone the browser is in;
        // a time still being edited has no offset yet and is read as local browser time.
        //
        // The current time is taken from the control store's poll_time rather than from the clock: a getter is
        // only re-evaluated when something reactive it reads has changed, and the clock is not reactive. Tying
        // it to the status poll means this turns true and false again on its own, one poll late at worst.
        in_ev_charge_period: (state) => {
            const { ev_charge_start: start, ev_charge_end: end } = state.config?.mode_dynamic ?? {}
            if (!start || !end) { return false }

            const from = Date.parse(start)
            const until = Date.parse(end)
            if (Number.isNaN(from) || Number.isNaN(until)) { return false }

            const now = useControlStore().poll_time?.toMillis() ?? Date.now()
            return from <= now && now <= until
        },
        error:          (state) => (state.error_status !== ''),
        status: (state) => (state.error_status !== '') ? '' : state.error_status,
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
        async fetch_config() {
            try {
                this.config = await this._make_fetch(`/config`)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while fetching config: ${err.msg}`
            }
        },
        async sync_general_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/general`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating general config: ${err.msg}`
            }
        },
        async sync_battery_inverters_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/battery_inverters`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating inverter config: ${err.msg}`
            }
        },
        async sync_solar_inverters_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/solar_inverters`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating solar inverter config: ${err.msg}`
            }
        },
        async sync_energy_meter_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/energy_meter`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating energy meter config: ${err.msg}`
            }
        },
        async sync_mode_manual_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/mode/manual`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating manual mode config: ${err.msg}`
            }
        },
        async sync_mode_static_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/mode/static`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating static mode config: ${err.msg}`
            }
        },
        async sync_mode_dynamic_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/mode/dynamic`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating dynamic mode config: ${err.msg}`
            }
        },
        async apply_bart_home_setup(cfg) {
            try {
                const resp = await this._make_fetch(`/config/bart_setup`, 'POST')
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while applying Bart home setup: ${err.msg}`
            }
        },
        async fetch_subsystem_types(cfg) {
            if (!this.subsystem_types) {
                try {
                    this.subsystem_types = await this._make_fetch(`/config/subsystem_types`)
                } catch (err) {
                    this.subsystem_types = null
                    this.error_status = `config store: error while fetching subsystem types: ${err.msg}`
                }
            }
        },
    }
})