<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { NDivider, NForm, NGrid, NFormItemGi, NSelect, NInputNumber, NInput, NFlex, NButton, NTimePicker, NDatePicker } from 'naive-ui'
import { useConfigStore } from '../stores/config'
import { storeToRefs } from 'pinia'

const config = useConfigStore()
const { mode_dynamic } = storeToRefs(config)

const fallback_options = [
    { label: 'idle', value: 1 },
    { label: 'manual', value: 2 },
    { label: 'static', value: 3 },
    { label: 'dynamic', value: 4 },
]

const hours = [...Array(24).keys()]
const minutes = [0, 15, 30, 45]

const form_ref = ref(null)

// the form items validate against this, so it must be an object also before the config has been fetched
const form_model = computed(() => (mode_dynamic.value instanceof Object ? mode_dynamic.value : {}))

const on_save = async () => {
  try {
    await form_ref.value?.validate()
  } catch {
    return  // the form shows what is wrong with each field
  }
  await config.sync_mode_dynamic_config(mode_dynamic.value)
}

const parse_percentage = (val) => {
    const v = val.replace('%', '').trim()
    return Math.round(Number(v) * 10) / 1000 // ensure 1 decimal
}

const format_percentage = (val) => {
    if (val === null) { return '' }
    return '' + Math.round(val * 1000) / 10
}

// The date picker takes null for "no value" and parses its value with this format, which carries no timezone
// offset. The backend keeps an unset time as an empty string, and stores a set one as a wall-clock time in the
// configured timezone with that zone's offset appended. Strip the offset on the way in, and hand the backend a
// plain wall-clock time on the way out: it applies the configured timezone itself. Anything the picker cannot
// parse becomes an invalid date, which makes it throw a RangeError as soon as a date is picked.
const EV_CHARGE_FORMAT = "yyyy-MM-dd'T'HH:mm:ss"

const ev_charge_time = (field) => computed({
    get: () => {
        const value = mode_dynamic.value?.[field]
        return value ? value.slice(0, 19) : null  // 'yyyy-MM-ddTHH:mm:ss', dropping the offset
    },
    set: (value) => {
        if (mode_dynamic.value instanceof Object) { mode_dynamic.value[field] = value ?? '' }
    },
})

const ev_charge_start = ev_charge_time('ev_charge_start')
const ev_charge_end = ev_charge_time('ev_charge_end')

// the backend requires both times to be set or both to be empty, so clearing the one clears the other
const on_clear_ev_charge = () => {
    ev_charge_start.value = null
    ev_charge_end.value = null
}

// Both EV charge times are set, or neither is, and the window runs forwards - the same rules the backend enforces.
// Both times are wall-clock times in the configured timezone, so comparing them as strings orders them correctly.
const rules = {
    ev_charge_start: {
        key: 'ev_charge',
        trigger: ['change', 'blur'],
        validator: () => {
            if (!ev_charge_start.value && ev_charge_end.value) {
                return new Error('Set a charge start time, or clear the end time')
            }
            return true
        },
    },
    ev_charge_end: {
        key: 'ev_charge',
        trigger: ['change', 'blur'],
        validator: () => {
            const start = ev_charge_start.value
            const end = ev_charge_end.value
            if (start && !end) { return new Error('Set a charge end time, or clear the start time') }
            if (start && end && end <= start) { return new Error('The charge end time must be later than the start time') }
            return true
        },
    },
}

// changing the one time decides whether the other is still valid, which the form does not re-check by itself
watch([ev_charge_start, ev_charge_end], () => {
    form_ref.value?.validate(undefined, (rule) => rule?.key === 'ev_charge').catch(() => {})
})


onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Dynamic Schedule Mode Config</h2>
  <n-divider />

  <n-form
  ref="form_ref"
  :model="form_model"
  :rules="rules"
  inline
  size="medium"
  label-placement="top"
  >
  <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
    <n-form-item-gi span="2" label="Price Update Time:" path="price_update_time">
        <n-time-picker
            v-model:formatted-value="mode_dynamic.price_update_time"
            format="HH:mm"
            value-format="HH:mm"
            :hours="hours"
            :minutes="minutes"
        />
    </n-form-item-gi>

    <n-form-item-gi span="4" label="Schedule Update Interval" path="update_interval">
        <n-input-number
            v-model:value="mode_dynamic.update_interval"
            :default-value="3600"
            :precision="0"
            :min="60" :max="86400"
            :show-button="false"
        >
            <template #suffix>seconds</template>
        </n-input-number>
    </n-form-item-gi>

    <n-form-item-gi span="4" label="Schedule Resolution" path="resolution">
        <n-input-number
            v-model:value="mode_dynamic.resolution"
            :default-value="15"
            :precision="0"
            :min="15" :max="60"
            :show-button="false"
        >
            <template #suffix>minutes</template>
        </n-input-number>
    </n-form-item-gi>

    <n-form-item-gi span="2" label="Fallback Mode" path="fallback_mode">
      <n-select
        v-model:value="mode_dynamic.fallback_mode"
        placeholder="Select fallback mode"
        :options="fallback_options"
      />
    </n-form-item-gi>

    <n-form-item-gi span="2" label="(Dis)charge efficiency" path="efficiency">
        <n-input-number
            v-model:value="mode_dynamic.efficiency"
            :default-value="0.95"
            :parse="parse_percentage"
            :format="format_percentage"
            :precision="3"
            :min="0" :max="1"
            :show-button="false"
        >
            <template #suffix>%</template>
        </n-input-number>
    </n-form-item-gi>

    <n-form-item-gi span="4 m:8 l:16" label="Enever API token" path="api_token">
        <n-input
            v-model:value="mode_dynamic.api_token"
            type="text"
            placeholder="API token..."
        >
        </n-input>
    </n-form-item-gi>

    <n-form-item-gi span="4" label="EV charge start" path="ev_charge_start">
        <n-date-picker
            v-model:formatted-value="ev_charge_start"
            :value-format="EV_CHARGE_FORMAT"
            type="datetime"
            clearable
            @clear="on_clear_ev_charge"
        />
    </n-form-item-gi>
    <n-form-item-gi span="4" label="EV charge end" path="ev_charge_end">
        <n-date-picker
            v-model:formatted-value="ev_charge_end"
            :value-format="EV_CHARGE_FORMAT"
            type="datetime"
            clearable
            @clear="on_clear_ev_charge"
        />
    </n-form-item-gi>
  </n-grid>

  <n-flex justify="space-between">
    <div>&nbsp;</div>
    <n-button @click="on_save" type="primary">Save</n-button>
  </n-flex>
</n-form>

  <n-divider />
  <dl>
    <dt><strong>Price Update Time</strong></dt>
    <dd>The time of day at which tomorrow's energy prices are fetched from the Enever API. Tomorrow's prices typically become available around 15:00–16:00 CET. The fetched prices are cached locally and used to compute the next optimal schedule.</dd>

    <dt><strong>Schedule Update Interval</strong></dt>
    <dd>How often (in seconds) the optimal charge/discharge schedule is recomputed using the latest prices and the current battery state-of-charge. A shorter interval keeps the schedule more accurate at the cost of more frequent recalculations.</dd>

    <dt><strong>Schedule Resolution</strong></dt>
    <dd>The time slot length (in minutes) used when building the schedule. Prices are aggregated to this resolution and the algorithm optimises one charge/discharge decision per slot. Smaller values give finer control but require more price data points to be available.</dd>

    <dt><strong>Fallback Mode</strong></dt>
    <dd>The control mode to fall back to when no valid schedule can be computed — for example when price data is unavailable. Choose a mode that results in a safe default behaviour for your installation.</dd>

    <dt><strong>Charge/discharge efficiency</strong></dt>
    <dd>The efficiency factor when charging or discharging the battery systemem (0–100 %). This is used by the scheduler to account for energy losses: charging costs more and discharging yields less than the nominal energy stored. A typical lithium battery system has an efficiency of 90–95 %.</dd>

    <dt><strong>EV charging period</strong></dt>
    <dd>Optionally, a period can be set for when an electric vehicle is charging (and consuming a significant amount of power). When executing the schedule, this period will be taken into account by skipping any battery charging scheduled during the same period.</dd>

  </dl>
</template>