
import { defineStore } from 'pinia'

export const useConfigStore = defineStore('configuration', {
    state: () => ({
        config: null,
        error_status: '',
    }),

    getters: {
        loaded:         (state) => state.config !== null,
        general:        (state) => (state.config === null) ? [] : state.config.general,
        inverters:      (state) => (state.config === null) ? [] : state.config.inverters,
        data_manager:   (state) => (state.config === null) ? -1 : state.config.data_manager,
        mode_manual:    (state) => (state.config === null) ? -1 : state.config.mode_manual,
        mode_static:    (state) => (state.config === null) ? -1 : state.config.mode_static,
        mode_dynamic:   (state) => (state.config === null) ? -1 : state.config.mode_dynamic,
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

            const resp = await fetch(`http://localhost:8080${path}`, options)
            // const resp = await fetch("/api"+path, options)
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
        async sync_inverter_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/inverters`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating inverter config: ${err.msg}`
            }
        },
        async sync_data_manager_config(cfg) {
            try {
                const resp = await this._make_fetch(`/config/data_manager`, 'POST', cfg)
            } catch (err) {
                this.config = null
                this.error_status = `config store: error while updating data manager config: ${err.msg}`
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
    }
})