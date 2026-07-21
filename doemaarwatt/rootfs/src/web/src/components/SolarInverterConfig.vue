<script setup>
import { onMounted, computed } from 'vue'
import { NDivider, NGrid, NForm, NFormItemGi, NInput, NInputNumber, NButton, NFlex, NIcon } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'
import { AddCircleOutline } from '@vicons/ionicons5'
import SolarInverterConfigItem from './SolarInverterConfigItem.vue'

const config = useConfigStore()
const { solar_inverters } = storeToRefs(config)

const on_removed = async (idx) => {
  console.log(`removing config ${idx}`)
  solar_inverters.value.splice(idx, 1)
}

const on_add = async () => {
  console.log(`appending a new config`)
  solar_inverters.value.push({
    name: '', host: '', port: 502,
    modbus_device_id: 3,
    connected_phase: 'ALL', enable: true,
  })
}

const on_save = async () => {
  await config.sync_solar_inverters_config(solar_inverters.value)
}

onMounted(async () => {
  await config.fetch_config()
  await config.fetch_subsystem_types()
})
</script>

<template>
  <h2>Solar Inverter Config</h2>
  <n-divider />

  <template v-for="(inv_cfg, idx) in solar_inverters" :key="idx">
    <SolarInverterConfigItem
      :idx="idx"
      v-model:name="inv_cfg.name"
      v-model:type="inv_cfg.type"
      v-model:enable="inv_cfg.enable"
      v-model:host="inv_cfg.host"
      v-model:port="inv_cfg.port"
      v-model:modbus_device_id="inv_cfg.modbus_device_id"
      v-model:connected_phase="inv_cfg.connected_phase"
      @removed="on_removed"
    />
  </template>

  <n-flex justify="space-between">
    <n-button @click="on_add" type="primary" secondary strong circle>
      <template #icon>
        <NIcon size="28">
          <AddCircleOutline />
        </NIcon>
      </template>
    </n-button>

    <n-button @click="on_save" type="primary">Save</n-button>
  </n-flex>

</template>
