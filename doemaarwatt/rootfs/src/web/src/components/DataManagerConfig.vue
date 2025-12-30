<script setup>
import { onMounted } from 'vue'
import { NDivider, NGrid, NForm, NFormItemGi, NInput, NInputNumber, NButton, NFlex } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const { data_manager } = storeToRefs(config)

const on_save = async () => {
  await config.sync_data_manager_config(data_manager.value)
}

onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Data Manager Config</h2>
  <n-divider />

  <p>
    Configuration for the SMA Data Manager.
  </p>

  <n-form>
    <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
        <n-form-item-gi span="3" label="Host" path="host">
            <n-input v-model:value="data_manager.host" placeholder="192.168..." />
        </n-form-item-gi>

        <n-form-item-gi span="1" label="Port" path="port">
            <n-input-number v-model:value="data_manager.port" min="1" max="65535" :show-button="false" />
        </n-form-item-gi>

        <n-form-item-gi span="2" label="Fuse max current" path="max_fuse_current">
            <n-input-number v-model:value="data_manager.max_fuse_current" min="1" max="150" :show-button="false">
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