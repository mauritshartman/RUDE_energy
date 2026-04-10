<script setup>
import { NH4, NCollapse, NCollapseItem, NText } from "naive-ui";
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
    Filler,
    TimeScale,
} from 'chart.js'
import 'chartjs-adapter-luxon';
import { Line } from 'vue-chartjs'
import { DateTime } from 'luxon'
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { useTimezone } from '../composables/useTimezone'

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

const control = useControlStore();
const { prices } = storeToRefs(control)
const { tz, now } = useTimezone()

const current_time = ref(now())

const price_update_ts = computed(() => DateTime.fromFormat(prices.value.update_ts, "yyyy-MM-dd'T'HH:mm:ssZZZ").setZone(tz.value))

const options = computed(() => ({
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
                    const dt = DateTime.fromMillis(context[0].parsed.x).setZone(tz.value)
                    return dt.toFormat('ccc dd MMM HH:mm')
                },
                label: (context) => {
                    const value = context.parsed.y
                    return `€ ${value.toFixed(6)} / kWh`
                }
            }
        }
    },
    scales: {
        x: {
            type: 'time',
            adapters: { date: { zone: tz.value } },
            time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
            grid: { color: '#303030', borderColor: 'grey', tickColor: 'grey' }
        },
        y: {
            title: { text: `Prices (€ / kWh)` },
            ticks: { callback: (val, idx, ticks) => `€ ${val.toFixed(3)}`}, // round to 3 decimals
        }
    }
}))

const price_chart_data = computed(() => {
    const ret = []

    const entries = Object.entries(prices.value.prices)
    entries.sort((a, b) => (a[0] - b[0])) // ensure chronological sorting

    // Find the index of the current slot: the last entry whose timestamp <= current_time
    let start_idx = 0
    for (let i = 0; i < entries.length; i++) {
        const t = DateTime.fromFormat(entries[i][0], "yyyy-MM-dd'T'HH:mm:ssZZZ").setZone(tz.value)
        if (t <= current_time.value) { start_idx = i } else { break }
    }

    let prev_p = null
    let prev_t = null
    let interval = null
   for (let i = start_idx; i < entries.length; i++) {
        const [ts, p] = entries[i]
        const t = DateTime.fromFormat(ts, "yyyy-MM-dd'T'HH:mm:ssZZZ").setZone(tz.value)

        if (prev_p !== null) { // copy the previous data point
            ret.push({ x: t.minus({ milliseconds: 1 }), y: prev_p })
        }
        ret.push({ x: t, y: p })

        if (prev_t !== null) { interval = t.diff(prev_t, 'minutes') }
        prev_p = p
        prev_t = t
    }
    if (interval !== null) { ret.push({ x: prev_t.plus(interval), y: prev_p }) }

    return ret
})

const avg_price = computed(() => {
    const vals = Object.values(prices.value.prices)
    if (vals.length === 0) return 0
    return vals.reduce((a, b) => a + b, 0) / vals.length
})

const price_chart_config = computed(() => {
    const lowest_price = Math.min(price_chart_data.value.reduce((a, b) => Math.min(a, b.y), Infinity))
    const highest_price = Math.min(price_chart_data.value.reduce((a, b) => Math.max(a, b.y), -Infinity))
    const avg = avg_price.value
    return {
        datasets: [{
            label: 'Prices (\u20AC / kWh)',
            data: price_chart_data.value,
            fill: { target: 'origin' },
            tension: 0.0,
            segment: {
                borderColor: (ctx) => ctx.p1.parsed.y >= avg ? 'rgb(255, 160, 50)' : 'rgb(75, 192, 75)',
                backgroundColor: (ctx) => {
                    const { ctx: canvasCtx, chartArea } = ctx.chart
                    if (!chartArea) return 'transparent'
                    const [r, g, b] = ctx.p1.parsed.y >= avg ? [255, 160, 50] : [75, 192, 75]
                    const gradient = canvasCtx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom)
                    gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.4)`)
                    gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0.0)`)
                    return gradient
                },
            },
        }, {
            label: 'Now',
            data: [{ x: current_time.value.minus({ milliseconds: 1}), y: lowest_price}, { x: current_time.value, y: highest_price }],
            borderColor: 'rgb(226, 99, 183)',
            tension: 0.0,
        }]
    }
})

// periodically update the current_time (plotted on the chart)
const timer = ref(null)
onMounted(() => {
    timer.value = setInterval(() => {
        current_time.value = now()
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
                    Exchange Prices
                </n-h4>
            </template>
            Current price: <n-text type="success">&euro; {{ prices.current_price.toFixed(3) }} per kWh</n-text>.
            Prices updated at {{ price_update_ts.toLocaleString(DateTime.DATETIME_MED) }}

            <Line :data="price_chart_config" :options="options" />
        </n-collapse-item>
    </n-collapse>
</template>
