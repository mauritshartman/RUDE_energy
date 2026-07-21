
import { defineStore } from 'pinia'
import { API_BASE } from './api'

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
        error:          (state) => (state.error_status !== ''),
        status:         (state) => (state.error_status !== '') ? '': state.error_status,
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