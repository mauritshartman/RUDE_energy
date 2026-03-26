<script setup>
import { NH4, NCollapse, NCollapseItem } from "naive-ui";
import { storeToRefs } from 'pinia'
import { useControlStore } from "../stores/control";
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    TimeScale,
} from 'chart.js'
import 'chartjs-adapter-luxon';
import { Line } from 'vue-chartjs'
import { DateTime } from 'luxon'
import { computed, ref, onMounted, onBeforeUnmount } from "vue";

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    TimeScale,
)

const COLORS = [
    'rgb(99, 179, 237)',
    'rgb(251, 146, 60)',
    'rgb(251, 182, 206)',
    'rgb(251, 211, 141)',
    'rgb(183, 148, 244)',
]

const control = useControlStore();
const { schedule } = storeToRefs(control)

const current_time = ref(DateTime.now())

const schedule_ts = computed(() => {
    if (!control.schedule_ts) return null
    return DateTime.fromISO(control.schedule_ts)
})

const options = ref({
    responsive: true,
    aspectRatio: 4,
    interaction: { intersect: false, mode: 'index' },
    elements: { point: { radius: 1 } },
    plugins: {
        legend: { position: 'bottom' },
        tooltip: {
            enabled: true,
            callbacks: {
                title: (context) => {
                    const dt = DateTime.fromMillis(context[0].parsed.x)
                    return dt.toFormat('ccc dd MMM HH:mm')
                },
                label: (context) => {
                    if (context.dataset.label === 'Now') return null
                    if (context.dataset.yAxisID === 'y_cost') {
                        const value = context.parsed.y
                        return `Cumulative cost: € ${value.toFixed(4)}`
                    }
                    const value = context.parsed.y
                    return `${context.dataset.label}: ${(value / 1000).toFixed(3)} kWh`
                }
            }
        }
    },
    scales: {
        x: {
            type: 'time',
            time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
            grid: { color: '#303030', borderColor: 'grey', tickColor: 'grey' }
        },
        y: {
            position: 'left',
            title: { display: true, text: 'State of Charge (Wh)' },
            ticks: { callback: (val) => `${(val / 1000).toFixed(1)} kWh` },
        },
        y_cost: {
            position: 'right',
            title: { display: true, text: 'Cumulative Cost (€)' },
            ticks: { callback: (val) => `€ ${val.toFixed(2)}` },
            grid: { color: (ctx) => ctx.tick.value === 0 ? '#606060' : 'transparent' },
        },
    }
})

const schedule_chart_config = computed(() => {
    if (!schedule.value || schedule.value.length === 0) return { datasets: [] }

    const slots = schedule.value
    const inv_names = Object.keys(slots[0].start_charge)

    // Build one dataset per inverter (left y-axis)
    const inv_datasets = inv_names.map((inv, idx) => {
        const data = slots.map(slot => ({
            x: DateTime.fromISO(slot.start_ts),
            y: slot.start_charge[inv],
        }))
        const last = slots[slots.length - 1]
        data.push({ x: DateTime.fromISO(last.end_ts), y: last.end_charge[inv] })

        return {
            label: inv,
            data,
            yAxisID: 'y',
            borderColor: COLORS[idx % COLORS.length],
            tension: 0.0,
        }
    })

    // Build cumulative cost dataset (right y-axis)
    // Each point is the running total of slot costs up to that slot's start time.
    const cost_data = []
    let cum_cost = 0
    for (const slot of slots) {
        cost_data.push({ x: DateTime.fromISO(slot.start_ts), y: cum_cost })
        cum_cost += slot.cost
    }
    const last = slots[slots.length - 1]
    cost_data.push({ x: DateTime.fromISO(last.end_ts), y: cum_cost })

    const cost_dataset = {
        label: 'Cumulative cost',
        data: cost_data,
        yAxisID: 'y_cost',
        borderColor: 'rgb(99, 226, 183)',
        tension: 0.0,
        pointRadius: 0,
    }

    // Determine SoC y-range for the "now" vertical line
    const all_y = slots.flatMap(s =>
        inv_names.flatMap(inv => [s.start_charge[inv], s.end_charge[inv]])
    )
    const y_min = Math.min(...all_y)
    const y_max = Math.max(...all_y)

    const now_dataset = {
        label: 'Now',
        data: [
            { x: current_time.value.minus({ milliseconds: 1 }), y: y_min },
            { x: current_time.value, y: y_max },
        ],
        yAxisID: 'y',
        borderColor: 'rgb(226, 99, 183)',
        tension: 0.0,
        pointRadius: 0,
    }

    return { datasets: [...inv_datasets, cost_dataset, now_dataset] }
})

// Periodically update the current_time line
const timer = ref(null)
onMounted(() => {
    timer.value = setInterval(() => {
        current_time.value = DateTime.now()
    }, 10 * 1000)
})
onBeforeUnmount(() => {
    clearInterval(timer.value)
    timer.value = null
})
</script>

<template>
    <n-collapse arrow-placement="right">
        <n-collapse-item>
            <template #header>
                <n-h4 prefix="bar">
                    Optimal schedule
                </n-h4>
            </template>
            <template v-if="schedule_ts">Schedule computed at {{ schedule_ts.toLocaleString(DateTime.DATETIME_MED) }}</template>

            <Line :data="schedule_chart_config" :options="options" />
        </n-collapse-item>
    </n-collapse>
</template>
