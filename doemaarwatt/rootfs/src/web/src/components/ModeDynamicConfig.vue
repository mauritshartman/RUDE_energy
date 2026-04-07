<script setup>
import { onMounted } from 'vue'
import { NDivider, NForm, NGrid, NFormItemGi, NSelect, NInputNumber, NInput, NFlex, NButton } from 'naive-ui'
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

const on_save = async () => {
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


onMounted(async () => { await config.fetch_config() })
</script>

<template>
  <h2>Dynamic Schedule Mode Config</h2>
  <n-divider />

  <n-form
  inline
  size="medium"
  label-placement="top"
  >
  <n-grid cols="4 s:4 m:8 l:16 xl:16" x-gap="10" responsive="screen">
    <n-form-item-gi span="2" label="Price Update Time:" path="time">
        <n-time-picker
            v-model:formatted-value="mode_dynamic.price_update_time"
            format="HH:mm"
            value-format="HH:mm"
            :hours="hours"
            :minutes="minutes"
        />
    </n-form-item-gi>

    <n-form-item-gi span="4" label="Schedule Update Interval" path="interval">
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

    <n-form-item-gi span="4" label="Enever API token" path="api_token">
        <n-input
            v-model:value="mode_dynamic.api_token"
            type="text"
            placeholder="API token..."
        >
        </n-input>
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
  </dl>
</template>