<script setup>
import { NIcon, NForm, NGrid, NFormItemGi, NTimePicker, NInputNumber, NSelect, NButton } from 'naive-ui'
import { CloseCircleOutline } from '@vicons/ionicons5'

const emit = defineEmits(['removed'])

const props = defineProps(['idx'])
const time = defineModel('time')
const battery_amount = defineModel('battery_amount')
const direction = defineModel('direction')
const solar_amount = defineModel('solar_amount')

const hours = [...Array(24).keys()]
const minutes = [0, 15, 30, 45]

const direction_options = [
    { label: 'standby', value: 'standby' },
    { label: 'charge', value: 'charge' },
    { label: 'discharge', value: 'discharge' },
]
</script>

<template>
    <n-form
        inline
        size="medium"
        label-placement="left"
    >
        <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
            <n-form-item-gi span="2" label="Time:" path="time">
                <n-time-picker
                    v-model:formatted-value="time"
                    format="HH:mm"
                    value-format="HH:mm"
                    :hours="hours"
                    :minutes="minutes"
                />
            </n-form-item-gi>

            <n-form-item-gi  span="4" label="Battery Amount:" path="battery_amount">
                <n-input-number v-model:value="battery_amount" min="0" max="10000" :show-button="false">
                    <template #suffix>W</template>
                </n-input-number>
            </n-form-item-gi>

            <n-form-item-gi span="3" label="Direction:" path="direction">
                <n-select
                v-model:value="direction"
                placeholder="Select direction"
                :options="direction_options"
                />
            </n-form-item-gi>

            <n-form-item-gi  span="4" label="Solar max power:" path="solar_amount">
                <n-input-number v-model:value="solar_amount" min="0" max="10000" :show-button="false">
                    <template #suffix>W</template>
                </n-input-number>
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
        </n-grid>
    </n-form>
</template>