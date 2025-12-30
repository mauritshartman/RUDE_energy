<script setup>
import { onMounted } from 'vue';
import { NDivider, NForm, NGrid, NFormItemGi, NSelect, NGridItem, NSwitch, NInputNumber, NFlex, NButton } from 'naive-ui'
import { useConfigStore } from '../stores/config';
import { storeToRefs } from 'pinia'

const config = useConfigStore()

const { general } = storeToRefs(config)

const mode_options = [
    { label: 'idle', value: 1 },
    { label: 'manual', value: 2 },
    { label: 'static', value: 3 },
    { label: 'dynamic', value: 4 },
]

const on_save = async () => {
  await config.sync_general_config(general.value)
}

onMounted(async () => { await config.fetch_config() })
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

        <n-form-item-gi span="4" label="Control loop delay" path="loop_delay">
            <n-input-number v-model:value="general.loop_delay" min="1" max="100" :show-button="false">
                <template #suffix>sec</template>
            </n-input-number>
        </n-form-item-gi>

        <n-grid-item span="0 m:4">
            <p>DoeMaarWatt operates in a loop. The loop_delay sets the delay in seconds between control actions.</p>
        </n-grid-item>
    </n-grid>
</n-form>

    <n-flex justify="space-between">
        <div>&nbsp;</div>
        <n-button @click="on_save" type="primary">Save</n-button>
    </n-flex>
</template>