<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue";
import { storeToRefs } from "pinia";
import { useControlStore } from '../stores/control';
import { useConfigStore } from "../stores/config";
import StatusTables from './StatusTables.vue';
import PricesGraph from "./PricesGraph.vue";
import ScheduleGraph from "./ScheduleGraph.vue";
import { DateTime } from "luxon";
import { useTimezone } from '../composables/useTimezone'

const control = useControlStore()
const config = useConfigStore();
const { tz } = useTimezone()

const { general } = storeToRefs(config);

const timer = ref();

onMounted(async () => {
  await control.fetch_status();
  await config.fetch_config();

  let ld = general.value.loop_delay;
  if (typeof ld === "undefined") {
    ld = 8;
  }
  console.log(`status refresh loop at ${ld} seconds`);

  timer.value = setInterval(async () => {
    console.log(`periodic status fetch (every ${ld} seconds)`);
    await control.fetch_status();
  }, ld * 1000);
});

onBeforeUnmount(() => {
  clearInterval(timer.value);
  timer.value = null;
});

</script>

<template>
    <h2>Main Page</h2>
    <p>
        <template v-if="control.running">Currently running in mode {{ control.mode }} ({{ control.mode_name }})</template>
        <template v-else>Not running</template>

        as of {{ control.update_time.setZone(tz).toLocaleString(DateTime.TIME_WITH_SECONDS) }}.
    </p>

    <ScheduleGraph v-if="control.schedule?.length" />
    <PricesGraph v-if="control.prices?.prices" />

    <StatusTables />
</template>