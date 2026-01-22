<script setup>
import { ref, onMounted, computed, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { DateTime } from 'luxon'
import { NScrollbar, NButton, NH4 } from 'naive-ui'
import { useControlStore } from '../stores/control'

const control = useControlStore()

const today = DateTime.now().startOf('day')
const d = ref(DateTime.now().startOf('day'))
const log = ref('')
const timer = ref(null)
const scrollbarRef = useTemplateRef('scrollbarRef')
const autoScroll = ref(true)

const at_today = computed(() => d.value.equals(today))

const scrollToBottom = () => {
    if (scrollbarRef.value) {
        setTimeout(() => {
            if (scrollbarRef.value) {
                scrollbarRef.value.scrollTo({ top: 999999, behavior: 'auto' })
            }
        }, 50)
    }
}

const handleScroll = (e) => {
    const { scrollTop, scrollHeight, offsetHeight } = e.target
    const isAtBottom = scrollHeight - scrollTop - offsetHeight < 10
    autoScroll.value = isAtBottom
}

const fetchLog = async () => {
    log.value = await control.fetch_log({ date: d.value.toFormat('yyyy-MM-dd') })

    if (autoScroll.value) {
        await nextTick()
        scrollToBottom()
    }
}

const to_next = async () => {
    d.value = d.value.plus({ days: 1 })
    await fetchLog()
}

const to_prev = async () => {
    d.value = d.value.minus({ days: 1 })
    await fetchLog()
}

const to_today = async () => {
    d.value = today
    await fetchLog()
}

onMounted(async () => {
    console.log(`log file refresh loop at 5 seconds`);
    await fetchLog()

    timer.value = setInterval(async () => {
        console.log(`periodic log refresh (every 5 seconds)`)
        await fetchLog()
    }, 5 * 1000)
})

onBeforeUnmount(() => {
    clearInterval(timer.value)
    timer.value = null
})
</script>

<template>
<div style="min-height: 40px; margin: 48px 0 16px 0;">
    <n-h4 prefix="bar" style="float:left;">
        Log file for {{ d.toLocaleString(DateTime.DATE_MED_WITH_WEEKDAY) }}
        <em v-if="at_today">(today)</em>
    </n-h4>

    <div style="float: right;">
        <n-button style="margin-left: 16px;" @click="to_prev">Previous Day</n-button>
        <n-button style="margin-left: 16px;" @click="to_today" :disabled="at_today">Today</n-button>
        <n-button style="margin-left: 16px;" @click="to_next" :disabled="at_today">Next Day</n-button>
    </div>
</div>

<n-scrollbar
    ref="scrollbarRef"
    @scroll="handleScroll"
    style="margin-top: 12px; max-height: 80vh; background-color: #111827; color: #f3f4f6; border: 1px solid #374151; border-radius: 4px;"
>
    <div class="log-content">{{ log }}</div>
</n-scrollbar>
</template>

<style scoped>
.log-content {
    padding: 16px;
    font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Monaco, Consolas, 'Courier New', monospace;
    font-size: 11px;
    white-space: pre-wrap;
}

</style>