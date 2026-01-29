<script setup>
import { onMounted, ref, computed } from 'vue';
import { NDivider, NFlex, NButton } from 'naive-ui'
import { useConfigStore } from '../stores/config';
import { storeToRefs } from 'pinia'
import { AddCircleOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler,
    TimeScale,
    plugins
} from 'chart.js'
import 'chartjs-adapter-luxon';
import { Line } from 'vue-chartjs'
import { DateTime } from 'luxon'
import ScheduleConfigItem from './ScheduleConfigItem.vue'

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend, Filler,
    TimeScale,
)

const config = useConfigStore()

const { mode_static } = storeToRefs(config)

const max_schedule_time = computed(() => {
    let ret = '00:00'
    for (const c of mode_static.value.schedule) {
        if (c.time > ret) { ret = c.time }
    }
    return ret
})

// for chartJS
const fca = (amount, direction) => {
    if (direction === 'standby' || direction === 'idle') { return 0 }
    else if (direction === 'charge') { return Math.abs(amount) / 1000 }
    else { return Math.abs(amount) / -1000 }
}

const loaded = ref(false)
const options = ref({
    responsive: true,
    aspectRatio: 4,
    scales: {
        x: {
            type: 'time',
            time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
            grid: { color: '#303030', borderColor: 'grey', tickColor: 'grey' }
        },
        y: {
            title: { text: 'Battery charge (kW)' },
            ticks: { callback: (val, idx, ticks) => `${Math.round(val * 10) / 10} kW`}, // round to 1 decimal
        },
    }
})

const schedule_chart_data = computed(() => {
    const start_ts = DateTime.now().startOf('day')

    if (mode_static.value.schedule.length === 0) {
        return [{ x: start_ts, y: 0 }, { x: start_ts.plus({ days: 1 }), y: 0 }]
    } else if (mode_static.value.schedule.length === 1) {
        const amount = fca(mode_static.value.schedule[0].amount, mode_static.value.schedule[0].direction)
        return [{ x: start_ts, y: amount }, { x: start_ts.plus({ days: 1 }), y: amount }]
    } else {
        const ret = []

        // ensure a data point at the start:
        if (mode_static.value.schedule[0].time !== '00:00') {
            const last_entry = mode_static.value.schedule[mode_static.value.schedule.length - 1]
            ret.push({ x: start_ts, y: fca(last_entry.amount, last_entry.direction) })
        }

        for (const c of mode_static.value.schedule) {
            const [hours, minutes] = c.time.split(':').map(Number)
            const change_ts = start_ts.plus({ hours: hours, minutes: minutes })

            if (ret.length > 0) { // copy the previous data point
                ret.push({
                    x: change_ts.minus({ seconds: 1 }),
                    y: ret[ret.length - 1].y
                })
            }
            ret.push({ x: change_ts, y: fca(c.amount, c.direction) })
        }

        // ensure a data point at the end:
        ret.push({ x: start_ts.plus({ days: 1 }), y: ret[ret.length - 1].y })

        return ret
    }
})

const schedule_chart_config = computed(() => {
    return {
        datasets: [{
            label: 'Battery charge amount (kW)',
            data: schedule_chart_data.value,
            fill: {
                target: 'origin',
                above: 'rgba(75, 192, 75, 0.2)',
                below: 'rgba(192, 75, 75, 0.2)',
            },
            borderColor: 'rgb(99, 226, 183)',
            tension: 0.0,
        }]
    }
})

const on_removed = async (idx) => {
    loaded.value = false
    console.log(`removing config ${idx}`)
    mode_static.value.schedule.splice(idx, 1)
    loaded.value = true
}

const on_add = async () => {
    loaded.value = false
    console.log(`appending a new schedule item`)
    mode_static.value.schedule.push({
        time: max_schedule_time.value, amount: 0, direction: 'standby'
    })
    loaded.value = true
}

const on_save = async () => {
    loaded.value = false
    mode_static.value.schedule.sort((a, b) => { // ensure sorting of the schedule
        if (a.time < b.time) { return -1 }
        if (a.time > b.time) { return 1 }
        return 0
    })
    await config.sync_mode_static_config(mode_static.value)
    loaded.value = true
}

onMounted(async () => {
    loaded.value = false
    await config.fetch_config()
    loaded.value = true
})
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

    <div>
        <Line v-if="loaded" :data="schedule_chart_config" :options="options" />
    </div>
</template>