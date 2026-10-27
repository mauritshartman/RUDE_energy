<script setup>
import { NIcon, NForm, NGrid, NFormItemGi, NInput, NInputNumber, NSelect, NSwitch, NButton, NDivider } from 'naive-ui'
import { CloseCircleOutline } from '@vicons/ionicons5'
import { storeToRefs } from "pinia";
import { useConfigStore } from '../stores/config'
import { computed } from 'vue';

const emit = defineEmits(['removed'])

const config = useConfigStore()

const props = defineProps(['idx'])
const name = defineModel('name')
const type = defineModel('type')
const enable = defineModel('enable')
const ignore_errors = defineModel('ignore_errors')
const host = defineModel('host')
const port = defineModel('port')
const connected_phase = defineModel('connected_phase')
const phase_mapping = defineModel('phase_mapping')

const ev_charger_types = computed(() => {
    const types = config.subsystem_types?.ev_chargers
    if (!types) { return [] }
    return Object.entries(types).map(([value, label]) => ({ value, label }))
})

const phase_options = [
    { label: 'L1', value: 'L1' },
    { label: 'L2', value: 'L2' },
    { label: 'L3', value: 'L3' },
    { label: 'All', value: 'ALL' },
]

const phase_mapping_options = [
    { label: 'straight mapping',    value: 'gridL1:evseL1,gridL2:evseL2,gridL3:evseL3' },
    { label: 'L1 & L2 swapped',     value: 'gridL1:evseL2,gridL2:evseL1,gridL3:evseL3' },
    { label: 'L2 & L3 swapped',     value: 'gridL1:evseL1,gridL2:evseL3,gridL3:evseL2' },
    { label: 'L1 & L3 swapped',     value: 'gridL1:evseL3,gridL2:evseL2,gridL3:evseL1' },
    { label: 'grid L1 -> EVSE L2, L2 -> L3, L3 -> L1', value: 'gridL1:evseL2,gridL2:evseL3,gridL3:evseL1' },
    { label: 'grid L1 -> EVSE L3, L2 -> L1, L3 -> L2', value: 'gridL1:evseL3,gridL2:evseL1,gridL3:evseL2' },
]

</script>

<template>
    <n-form
        inline
        size="medium"
        label-placement="top"
    >
        <n-grid cols="3 s:3 m:6 l:16" x-gap="10" responsive="screen">
            <n-form-item-gi span="3" label="Name" path="name">
                <n-input v-model:value="name" placeholder="EV charger name" />
            </n-form-item-gi>

            <n-form-item-gi span="3" label="Type" path="type">
                <n-select
                    v-model:value="type"
                    placeholder="Select type"
                    :options="ev_charger_types"
                />
            </n-form-item-gi>

            <n-form-item-gi span="3" label="Host : port">
                <n-input v-model:value="host" placeholder="192.168..." />
                &nbsp;
                <n-input-number v-model:value="port" min="1" max="65535" :show-button="false" />
            </n-form-item-gi>

            <n-form-item-gi label="Phase" path="connected_phase">
                <n-select
                    v-model:value="connected_phase"
                    placeholder="Select phase"
                    :options="phase_options"
                />
            </n-form-item-gi>
            <n-form-item-gi span="3" label="Mapping" path="phase_mapping">
                <n-select
                    v-model:value="phase_mapping"
                    placeholder="Phase mapping"
                    :options="phase_mapping_options"
                />
            </n-form-item-gi>

            <n-form-item-gi :label="(enable) ? 'Enabled' : 'Disabled'" path="enable">
                <n-switch v-model:value="enable" />
            </n-form-item-gi>

            <n-form-item-gi label="Ignore errors" path="ignore_errors">
                <n-switch v-model:value="ignore_errors" />
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