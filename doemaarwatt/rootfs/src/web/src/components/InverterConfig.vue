<script setup>
import { onMounted } from 'vue';
import { NDivider, NFlex, NButton } from 'naive-ui'
import { useConfigStore } from '../stores/config';
import { storeToRefs } from 'pinia'
import { AddCircleOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui';
import InverterConfigItem from './InverterConfigItem.vue';


const config = useConfigStore()

const { inverters } = storeToRefs(config)

const on_removed = async (idx) => {
  console.log(`removing config ${idx}`)
  inverters.value.splice(idx, 1)
}

const on_add = async () => {
  console.log(`appending a new config`)
  inverters.value.push({
    name: '', host: '', port: 502, battery_charge_limit: 0, battery_discharge_limit: 0, connected_phase: 'L1', enable: true,
  })
}

const on_save = async () => {
  await config.sync_inverter_config(inverters.value)
}

onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Inverter Config</h2>
  <n-divider />

  <template v-for="(inv_cfg, idx) in inverters" :key="idx">
    <InverterConfigItem
      :idx="idx"
      v-model:name="inv_cfg.name"
      v-model:enable="inv_cfg.enable"
      v-model:host="inv_cfg.host"
      v-model:port="inv_cfg.port"
      v-model:battery_charge_limit="inv_cfg.battery_charge_limit"
      v-model:battery_discharge_limit="inv_cfg.battery_discharge_limit"
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

<style scoped>
</style>
