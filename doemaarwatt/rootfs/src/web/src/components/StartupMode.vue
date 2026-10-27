<script setup>
import { onMounted, computed } from 'vue';
import {
    NDivider, NForm, NGrid, NFormItemGi, NSelect, NGridItem, NSwitch, NInput, NInputNumber, NFlex, NButton,
    NAlert, NCheckbox
} from 'naive-ui'
import { useConfigStore } from '../stores/config';
import { useControlStore } from '../stores/control';
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const control = useControlStore()

const { general } = storeToRefs(config)
const { running } = storeToRefs(control)

// The checks configured for this installation (config.safety_checks), described by the catalogue the backend
// offers (config.available_safety_checks) and ordered by ascending priority.
//
// Both sides are guarded. The two are fetched separately in onMounted, so the configured checks are known a
// moment before the catalogue that describes them (and the catalogue stays null when its fetch fails). A
// configured check the backend no longer offers is skipped rather than rendered without a description.
const checks_in_prio_range = (lowest_prio, highest_prio) => computed(() => {
    const catalogue = config.available_safety_checks
    if (!catalogue) { return [] }  // nothing to describe the checks with (yet)

    return Object.keys(config.safety_checks ?? {})
        .filter(name => catalogue[name])
        .map(name => ({
            name,
            prio: catalogue[name].prio,
            descr: catalogue[name].description,
            always_on: catalogue[name].always_on === true,  // applied whatever the setting says, so not switchable
        }))
        .filter(({ prio }) => lowest_prio <= prio && prio <= highest_prio)
        .sort((a, b) => a.prio - b.prio)
})

const safety_check_names = checks_in_prio_range(0, 99)        // safety checks
const preferred_check_names = checks_in_prio_range(100, 999)  // preferred behaviour checks

const _all_timezones = Intl.supportedValuesOf('timeZone').filter(tz => tz !== 'Europe/Amsterdam')
const timezone_options = [
    { label: 'Europe/Amsterdam', value: 'Europe/Amsterdam' },
    ..._all_timezones.map(tz => ({ label: tz, value: tz })),
]

const mode_options = [
    { label: 'idle', value: 1 },
    { label: 'manual', value: 2 },
    { label: 'static', value: 3 },
    { label: 'dynamic', value: 4 },
]

const on_save = async () => {
  await config.sync_general_config(general.value)
  await control.fetch_status()
}

const on_bart = async () => {
    await config.apply_bart_home_setup()
    await config.fetch_config()
}

onMounted(async () => {
    await config.fetch_available_safety_checks()
    await config.fetch_config()
})
</script>

<template>
    <h2>General Configuration</h2>
    <n-divider />

    <n-form
        inline
        size="medium"
        label-placement="left"
    >
    <n-grid cols="4 s:4 m:8 l:8 xl:8" x-gap="10" responsive="screen">
        <n-form-item-gi span="4" label="Startup mode:" path="general.mode">
            <n-select
                v-model:value="general.mode"
                placeholder="Select startup mode"
                :options="mode_options"
            />
        </n-form-item-gi>
        <n-grid-item span="0 m:4">
            <p>
                Please select the startup mode of DoeMaarWatt. DoeMaarWatt operates in various modes, those being:
            </p>
            <ol>
                <li><em>idle</em>: No active control, just read device output</li>
                <li><em>manual</em>: Actively control with a continuous charge or discharge power</li>
                <li><em>static</em>: Actively control based on a fixed static schedule</li>
                <li><em>dynamic</em>: Actively control based on dynamic prices</li>
            </ol>
        </n-grid-item>

        <n-form-item-gi span="4" label="Debug output:" path="debug">
            <n-switch v-model:value="general.debug" />
        </n-form-item-gi>
        <n-grid-item span="0 m:4">
            <p>
                Whether to send additional debugging output, such as Modbus messages, to the addon log.
            </p>
        </n-grid-item>

        <n-form-item-gi span="0 m:4" label="Control loop delay:" path="loop_delay">
            <n-input-number v-model:value="general.loop_delay" min="1" max="100" :show-button="false">
                <template #suffix>sec</template>
            </n-input-number>
        </n-form-item-gi>
        <n-grid-item span="0 m:4">
            <p>DoeMaarWatt operates in a loop. The loop_delay sets the delay in seconds between control actions.</p>
        </n-grid-item>

        <n-form-item-gi span="0 m:4" label="Timezone:" path="timezone">
            <n-select
                v-model:value="general.timezone"
                :options="timezone_options"
                filterable
            />
        </n-form-item-gi>
        <n-grid-item span="0 m:4">
            <p>Your local IANA timezone name. DST is handled automatically.</p>
        </n-grid-item>

        <n-form-item-gi span="0 m:4" label="Long-lived access token:" path="supervisor_token">
            <n-input
            v-model:value="general.supervisor_token"
            type="text"
            placeholder="Long-lived access token..."
        >
        </n-input>
        </n-form-item-gi>
        <n-grid-item span="0 m:4">
            <p>Long-lived access token, used for Home Assistant push notifications. Can be set from your profile (lower left) -> Security -> Long-lived access tokens.</p>
        </n-grid-item>


        <n-grid-item span="4 s:4 m:8 l:8 xl:8">
            <h3>Safety Checks</h3>
            <n-divider />
        </n-grid-item>

        <template v-for="safety_check in safety_check_names" :key="safety_check.name">
            <n-form-item-gi span="4 m:3">
                <n-checkbox
                    :checked="safety_check.always_on ? true : config.safety_checks[safety_check.name]"
                    :disabled="safety_check.always_on"
                    @update:checked="value => config.safety_checks[safety_check.name] = value"
                >
                    {{ safety_check.name }}
                </n-checkbox>
            </n-form-item-gi>
            <n-grid-item span="0 m:1">
                <p><em>Prio {{ safety_check.prio }}</em></p>
            </n-grid-item>
            <n-grid-item span="0 m:4">
                <p>
                    {{ safety_check.descr }}
                    <em v-if="safety_check.always_on">This check protects the installation itself and is always applied.</em>
                </p>
            </n-grid-item>
        </template>

        <n-grid-item span="4 s:4 m:8 l:8 xl:8">
            <h3>Preferred Behavior</h3>
            <n-divider />
        </n-grid-item>

        <template v-for="safety_check in preferred_check_names" :key="safety_check.name">
            <n-form-item-gi span="4 m:3">
                <n-checkbox v-model:checked="config.safety_checks[safety_check.name]" size="large">
                    {{ safety_check.name }}
                </n-checkbox>
            </n-form-item-gi>
            <n-grid-item span="0 m:1">
                <p><em>Prio {{ safety_check.prio }}</em></p>
            </n-grid-item>
            <n-grid-item span="0 m:4">
                <p>{{ safety_check.descr }}</p>
            </n-grid-item>
        </template>

    </n-grid>
</n-form>

    <n-alert v-if="running" type="warning" style="margin-bottom: 12px">
        The controller is currently running. Saving will stop it.
    </n-alert>

    <n-flex justify="space-between">
        <div>&nbsp;</div>
        <n-button @click="on_bart" type="warning">Apply Bart Home Setup</n-button>
        <div>&nbsp;</div>
        <n-button @click="on_save" type="primary">Save</n-button>
    </n-flex>
</template>