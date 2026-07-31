<script setup>
import { ref, onMounted, computed, onBeforeUnmount, nextTick, useTemplateRef } from 'vue'
import { DateTime } from 'luxon'
import { NScrollbar, NButton, NH4, NInput } from 'naive-ui'
import { useControlStore } from '../stores/control'
import { useTimezone } from '../composables/useTimezone'
import { API_BASE } from '../stores/api'

const control = useControlStore()
const { now } = useTimezone()

const today = computed(() => now().startOf('day'))
const d = ref(now().startOf('day'))
const log = ref('')
const logOffset = ref(0)   // byte offset into the current day's log file that we already hold in `log`
const timer = ref(null)
const scrollbarRef = useTemplateRef('scrollbarRef')
const autoScroll = ref(true)
// Format a byte count as a rounded MB / KB / bytes string.
const formatBytes = (bytes) => {
    if (bytes >= 1024 * 1024) { return `${(bytes / (1024 * 1024)).toFixed(1)} MB` }
    if (bytes >= 1024) { return `${Math.round(bytes / 1024)} KB` }
    return `${bytes} bytes`
}
// logOffset is the daily log file's total size in bytes (reported by the backend as X-Log-Size)
const logSize = computed(() => formatBytes(logOffset.value))
// filter options
const filter = ref(['INFO', 'ERROR', 'FATAL'])
const filterTerm = ref('')  // free-text filter term the user types into the input field

// Escape a string so it can be used literally inside a RegExp.
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const filtered_log = computed(() => {
    // A line matches when it contains at least one of the selected levels (DEBUG OR INFO OR ERROR OR FATAL)
    // AND, if a search term is entered, also contains that term. With no term it is just the level OR filter.
    const levels = filter.value.filter(Boolean)
    if (levels.length === 0) { return '' }   // no level selected -> nothing to show
    const term = filterTerm.value.trim()

    // Single regex pass over the raw log (efficient for large files, case-insensitive via the `i` flag):
    // `^(?=.*(?:levels))(?=.*term).*$` with the `m` flag requires both a level and the term on the same line.
    // `.` never matches `\n`, so each lookahead only inspects the current line.
    const levelAlt = levels.map(escapeRegExp).join('|')
    const termLookahead = term ? `(?=.*${escapeRegExp(term)})` : ''
    const re = new RegExp(`^(?=.*(?:${levelAlt}))${termLookahead}.*$`, 'gim')
    const matches = log.value.match(re)
    return matches ? matches.join('\n') : ''
})

const at_today = computed(() => d.value.equals(today.value))

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

// Monotonic token: if a newer fetch starts (e.g. the user changes the date) while an older one is still in
// flight, the older one's result is discarded instead of corrupting the buffer.
let fetchGen = 0

const fetchLog = async () => {
    const gen = ++fetchGen
    const date = d.value.toFormat('yyyy-MM-dd')
    const sentOffset = logOffset.value
    const r = await control.fetch_log({ date, offset: sentOffset })
    if (gen !== fetchGen) { return }   // superseded by a newer fetch -> discard this stale result
    if (!r) { return }                 // fetch error: keep the current buffer, retry on the next tick

    // r.start === sentOffset -> a contiguous delta, so append it; otherwise the server returned the whole file
    // (initial load, or the file was rotated) -> replace the buffer with it.
    log.value = (r.start === sentOffset) ? log.value + r.text : r.text
    logOffset.value = r.size

    if (autoScroll.value) {
        await nextTick()
        scrollToBottom()
    }
}

// Fully reload the selected date's log (used on date changes): reset the incremental state, then fetch.
const reloadLog = async () => {
    logOffset.value = 0
    log.value = ''
    await fetchLog()
}

// Return a click handler that toggles `word` in the filter array (add if absent, remove if present).
const toggle_filter = (word) => () => {
    const i = filter.value.indexOf(word)
    if (i === -1) {
        filter.value.push(word)
    } else {
        filter.value.splice(i, 1)
    }
}

const toggle_debug_filter = toggle_filter('DEBUG')
const toggle_info_filter = toggle_filter('INFO')
const toggle_error_filter = toggle_filter('ERROR')
const toggle_fatal_filter = toggle_filter('FATAL')

const to_next = async () => {
    d.value = d.value.plus({ days: 1 })
    await reloadLog()
}

const to_prev = async () => {
    d.value = d.value.minus({ days: 1 })
    await reloadLog()
}

const to_today = async () => {
    d.value = today.value
    await reloadLog()
}

const downloadLog = () => {
    // Download via a real navigation to the backend endpoint (Content-Disposition: attachment). This works
    // inside the Home Assistant ingress iframe where a client-side Blob download can be blocked. API_BASE
    // already carries the ingress path prefix. The filename is set by the server's Content-Disposition header.
    const a = document.createElement('a')
    a.href = `${API_BASE}/log/download?date=${d.value.toFormat('yyyy-MM-dd')}`
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
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
<div class="log-header">
    <div class="log-header-title">
        <n-h4 prefix="bar" style="margin: 0;">
            Log file for {{ d.toLocaleString(DateTime.DATE_MED_WITH_WEEKDAY) }}
            <em v-if="at_today">(today)</em>
        </n-h4>
    </div>

    <div class="log-header-filters">
        <n-button @click="toggle_debug_filter" :type="filter.includes('DEBUG') ? 'primary' : 'default'">DEBUG</n-button>
        <n-button @click="toggle_info_filter" :type="filter.includes('INFO') ? 'primary' : 'default'">INFO</n-button>
        <n-button @click="toggle_error_filter" :type="filter.includes('ERROR') ? 'primary' : 'default'">ERROR</n-button>
        <n-button @click="toggle_fatal_filter" :type="filter.includes('FATAL') ? 'primary' : 'default'">FATAL</n-button>
        <n-input v-model:value="filterTerm" placeholder="filter…" clearable style="width: 150px;" />
    </div>

    <div class="log-header-nav">
        <n-button @click="to_prev">Previous Day</n-button>
        <n-button @click="to_today" :disabled="at_today">Today</n-button>
        <n-button @click="to_next" :disabled="at_today">Next Day</n-button>
        <n-button @click="downloadLog" :disabled="!log" type="primary" secondary>Download</n-button>
    </div>
</div>

<n-scrollbar
    ref="scrollbarRef"
    @scroll="handleScroll"
    style="margin-top: 12px; max-height: 80vh; background-color: #111827; color: #f3f4f6; border: 1px solid #374151; border-radius: 4px;"
>
    <div class="log-content">{{ filtered_log }}</div>
</n-scrollbar>

<div class="log-size">Total log size: {{ logSize }}</div>
</template>

<style scoped>
/* Header: three sections on one row - title left, filters centered, nav/download right.
   The title and nav both flex:1 so the filters section stays truly centered regardless of their widths. */
.log-header {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 40px;
    margin: 48px 0 16px 0;
}

.log-header-title {
    flex: 1;
    display: flex;
    justify-content: flex-start;
}

.log-header-filters {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
}

.log-header-nav {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
}

/* Narrow screens: stack the three sections vertically */
@media (max-width: 1024px) {
    .log-header {
        flex-direction: column;
        align-items: stretch;
    }
    .log-header-title,
    .log-header-filters,
    .log-header-nav {
        flex: initial;
    }
    .log-header-nav {
        justify-content: center;
    }
}

.log-content {
    padding: 16px;
    font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', Menlo, Monaco, Consolas, 'Courier New', monospace;
    font-size: 11px;
    white-space: pre-wrap;
}

/* Small, muted, right-aligned log-size caption below the scrollbar */
.log-size {
    text-align: right;
    font-size: 12px;
    color: #9ca3af;
    margin-top: 4px;
}

</style>