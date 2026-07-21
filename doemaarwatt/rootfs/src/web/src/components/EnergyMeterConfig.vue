<script setup>
import { onMounted, computed } from 'vue'
import { NDivider, NGrid, NForm, NFormItemGi, NInput, NInputNumber, NButton, NFlex, NSelect } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const { energy_meter } = storeToRefs(config)

const on_save = async () => {
  await config.sync_energy_meter_config(energy_meter.value)
}

const energy_meter_types = computed(() => {
    const types = config.subsystem_types?.energy_meters
    if (!types) { return [] }
    return Object.entries(types).map(([value, label]) => ({ value, label }))
})

onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Energy Meter Config</h2>
  <n-divider />

  <p>
    Configuration for the grid connection energy meter.
  </p>

  <n-form>
    <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
        <n-form-item-gi span="4" label="Type" path="type">
          <n-select
              v-model:value="energy_meter.type"
              placeholder="Select type"
              :options="energy_meter_types"
          />
        </n-form-item-gi>

        <n-form-item-gi span="3" label="Host" path="host">
            <n-input v-model:value="energy_meter.host" placeholder="192.168..." />
        </n-form-item-gi>

        <n-form-item-gi span="1" label="Port" path="port">
            <n-input-number v-model:value="energy_meter.port" min="1" max="65535" :show-button="false" />
        </n-form-item-gi>

        <n-form-item-gi span="2" label="Fuse max current" path="max_fuse_current">
            <n-input-number v-model:value="energy_meter.max_fuse_current" min="1" max="150" :show-button="false">
                <template #suffix>A</template>
            </n-input-number>
        </n-form-item-gi>
    </n-grid>

    <n-flex justify="space-between">
        <div>&nbsp;</div>
        <n-button @click="on_save" type="primary">Save</n-button>
    </n-flex>
  </n-form>
</template>