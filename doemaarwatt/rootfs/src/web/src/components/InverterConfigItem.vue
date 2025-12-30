<script setup>
import { NIcon, NForm, NGrid, NFormItemGi, NInput, NInputNumber, NSelect, NSwitch, NButton, NDivider } from 'naive-ui'
import { CloseCircleOutline } from '@vicons/ionicons5'

const emit = defineEmits(['removed'])

const props = defineProps(['idx'])
const name = defineModel('name')
const enable = defineModel('enable')
const host = defineModel('host')
const port = defineModel('port')
const battery_charge_limit = defineModel('battery_charge_limit')
const battery_discharge_limit = defineModel('battery_discharge_limit')
const connected_phase = defineModel('connected_phase')

const phase_options = [
    { label: 'L1', value: 'L1' },
    { label: 'L2', value: 'L2' },
    { label: 'L3', value: 'L3' },
]
</script>

<template>
    <n-form
        inline
        size="medium"
        label-placement="top"
    >
        <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
            <n-form-item-gi span="4" label="Name" path="name">
                <n-input v-model:value="name" placeholder="inverter name" />
            </n-form-item-gi>

            <n-form-item-gi span="3" label="Host" path="host">
                <n-input v-model:value="host" placeholder="192.168..." />
            </n-form-item-gi>

            <n-form-item-gi  span="1" label="Port" path="port">
                <n-input-number v-model:value="port" min="1" max="65535" :show-button="false" />
            </n-form-item-gi>

            <n-form-item-gi  span="2" label="Battery charge limit" path="battery_charge_limit">
                <n-input-number v-model:value="battery_charge_limit" min="0" max="100000" :show-button="false">
                    <template #suffix>W</template>
                </n-input-number>
            </n-form-item-gi>

            <n-form-item-gi  span="2" label="Battery discharge limit" path="battery_discharge_limit">
                <n-input-number v-model:value="battery_discharge_limit" min="0" max="100000" :show-button="false">
                    <template #suffix>W</template>
                </n-input-number>
            </n-form-item-gi>

            <n-form-item-gi span="2" label="Connected Phase" path="connected_phase">
                <n-select
                    v-model:value="connected_phase"
                    placeholder="Select phase"
                    :options="phase_options"
                />
            </n-form-item-gi>

            <n-form-item-gi :label="(enable) ? 'Enabled' : 'Disabled'" path="enable">
                <n-switch v-model:value="enable" />
            </n-form-item-gi>

            <n-form-item-gi>
                <n-button @click="emit('removed', props.idx)" type="error" secondary strong circle>
                    <template #icon>
                        <NIcon size="28">
                            <CloseCircleOutline />
                        </NIcon>
                    </template>
                </n-button>
            </n-form-item-gi>

            <n-form-item-gi span="4 s:4 m:0 l:0 xl:0">
                <n-divider />
            </n-form-item-gi>
        </n-grid>

    </n-form>
</template>