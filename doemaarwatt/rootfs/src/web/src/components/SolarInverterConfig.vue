<script setup>
import { onMounted } from 'vue'
import { NDivider, NGrid, NForm, NFormItemGi, NInput, NInputNumber, NButton, NFlex } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const { solar_inverter } = storeToRefs(config)

const on_save = async () => {
  await config.sync_solar_inverter_config(solar_inverter.value)
}

onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Solar Inverter Config</h2>
  <n-divider />

  <p>
    Configuration for the SMA Solar Inverter.
  </p>

  <n-form>
    <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
        <n-form-item-gi span="3" label="Host" path="host">
            <n-input v-model:value="solar_inverter.host" placeholder="192.168..." />
        </n-form-item-gi>

        <n-form-item-gi span="1" label="Port" path="port">
            <n-input-number v-model:value="solar_inverter.port" min="1" max="65535" :show-button="false" />
        </n-form-item-gi>

        <n-form-item-gi span="1" label="Port" path="port">
            <n-input-number v-model:value="solar_inverter.modbus_device_id" min="1" max="65535" :show-button="false" />
        </n-form-item-gi>
    </n-grid>

    <n-flex justify="space-between">
        <div>&nbsp;</div>
        <n-button @click="on_save" type="primary">Save</n-button>
    </n-flex>
  </n-form>
</template>
