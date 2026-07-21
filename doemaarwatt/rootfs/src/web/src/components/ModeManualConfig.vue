<script setup>
import { onMounted } from 'vue'
import { NDivider, NForm, NGrid, NFormItemGi, NSelect, NInputNumber, NFlex, NButton } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const { mode_manual } = storeToRefs(config)

const direction_options = [
    { label: 'standby', value: 'standby' },
    { label: 'charge', value: 'charge' },
    { label: 'discharge', value: 'discharge' },
]

const on_save = async () => {
  await config.sync_mode_manual_config(mode_manual.value)
}

onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Manual Mode Config</h2>
  <n-divider />

  <n-form
  inline
  size="medium"
  label-placement="top"
  >
  <n-grid cols="4 s:4 m:8 l:12 xl:12" x-gap="10" responsive="screen">
    <n-form-item-gi span="4" label="Direction" path="direction">
      <n-select
        v-model:value="mode_manual.direction"
        placeholder="Select direction"
        :options="direction_options"
      />
    </n-form-item-gi>

    <n-form-item-gi span="4" label="Battery charge/discharge amount (per phase)" path="battery_amount">
      <n-input-number v-model:value="mode_manual.battery_amount" min="0" max="10000" :show-button="false">
        <template #suffix>W</template>
      </n-input-number>
    </n-form-item-gi>

    <n-form-item-gi span="4" label="Solar max power (per pahse)" path="solar_amount">
      <n-input-number v-model:value="mode_manual.solar_amount" min="0" max="10000" :show-button="false">
        <template #suffix>W</template>
      </n-input-number>
    </n-form-item-gi>
  </n-grid>

  <n-flex justify="space-between">
    <div>&nbsp;</div>
    <n-button @click="on_save" type="primary">Save</n-button>
  </n-flex>
</n-form>

  <p>
    Define the direction (charge or discharge) and the amount of power while operating in <em>manual mode</em>.
    The charge/discharge power is commanded to each individual battery inverter, while a maximum setpoint power limit
    is commanded to each solar inverter. Note that the setpoint power limit is per phase.
  </p>
</template>