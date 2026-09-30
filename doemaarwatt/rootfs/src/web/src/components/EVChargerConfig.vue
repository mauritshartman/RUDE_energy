<script setup>
import { onMounted, computed } from 'vue'
import { NDivider, NGrid, NForm, NFormItemGi, NInput, NInputNumber, NButton, NFlex, NIcon } from 'naive-ui'
import { useConfigStore } from '../stores/config.js'
import { storeToRefs } from 'pinia'
import { AddCircleOutline } from '@vicons/ionicons5'
import EVChargerConfigItem from './EVChargerConfigItem.vue'

const config = useConfigStore()
const { ev_chargers } = storeToRefs(config)

const on_removed = async (idx) => {
  console.log(`removing config ${idx}`)
  ev_chargers.value.splice(idx, 1)
}

const on_add = async () => {
  console.log(`appending a new config`)
  ev_chargers.value.push({
    name: '', host: '', port: 502,
    connected_phase: 'ALL', enable: true,
  })
}

const on_save = async () => {
  await config.sync_ev_chargers_config(ev_chargers.value)
}

onMounted(async () => {
  await config.fetch_config()
  await config.fetch_subsystem_types()
})
</script>

<template>
  <h2>EV Chargers Config</h2>
  <n-divider />

  <template v-for="(ev_cfg, idx) in ev_chargers" :key="idx">
    <EVChargerConfigItem
      :idx="idx"
      v-model:name="ev_cfg.name"
      v-model:type="ev_cfg.type"
      v-model:enable="ev_cfg.enable"
      v-model:host="ev_cfg.host"
      v-model:port="ev_cfg.port"
      v-model:connected_phase="ev_cfg.connected_phase"
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
