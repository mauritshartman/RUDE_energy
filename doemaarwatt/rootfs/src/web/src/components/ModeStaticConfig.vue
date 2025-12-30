<script setup>
import { onMounted } from 'vue';
import { NDivider, NFlex, NButton } from 'naive-ui'
import { useConfigStore } from '../stores/config';
import { storeToRefs } from 'pinia'
import { AddCircleOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui';
import ScheduleConfigItem from './ScheduleConfigItem.vue';

const config = useConfigStore()

const { mode_static } = storeToRefs(config)

const on_removed = async (idx) => {
  console.log(`removing config ${idx}`)
  mode_static.value.schedule.splice(idx, 1)
}

const on_add = async () => {
  console.log(`appending a new schedule item`)
  mode_static.value.schedule.push({
    time: '00:00', amount: 0, direction: 'standby'
  })
}

const on_save = async () => {
    mode_static.value.schedule.sort((a, b) => { // ensure sorting of the schedule
        if (a.time < b.time) { return -1 }
        if (a.time > b.time) { return 1 }
        return 0
    })
    await config.sync_mode_static_config(mode_static.value)
}

onMounted(async () => { await config.fetch_config() })
</script>

<template>
    <h2>Static Mode Configuration</h2>
    <n-divider />

    <template v-for="(inv_cfg, idx) in mode_static.schedule" :key="idx">
        <ScheduleConfigItem
            :idx="idx"
            v-model:time="inv_cfg.time"
            v-model:amount="inv_cfg.amount"
            v-model:direction="inv_cfg.direction"
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

    <p>
    Define a static charge / discharge schedule that is used in the <em>static schedule</em> mode.
    By clicking the <n-button type="primary" secondary strong circle size="tiny"><NIcon size="16"><AddCircleOutline /></NIcon></n-button> button,
    you can add moments in the schedule on which it changes. Each moment is defined by a time, a <em>direction</em> (being idle, charging or discharging),
    and an amount in Watts.
    </p>
</template>