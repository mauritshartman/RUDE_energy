<script setup>
import { h, ref } from "vue";
import {
  HomeOutline,
  HardwareChipOutline,
  SettingsOutline,
  BatteryChargingOutline,
  CalendarOutline,
  NewspaperOutline,
  HandLeftOutline,
  BarChartOutline,
  AppsOutline,
  FileTrayFullOutline,
  SunnyOutline,
} from "@vicons/ionicons5";
import { NIcon, NMenu, NButton, NGrid, NGi } from "naive-ui";
import { RouterLink } from "vue-router";
import { useControlStore } from "../stores/control";

const control = useControlStore();

const loading = ref(false)

const render_icon = (icon) => {
  return () => h(NIcon, null, { default: () => h(icon) });
};

const menu_options = ref([
  {
    label: () =>
      h(RouterLink, { to: { name: "home" } }, { default: () => "Home" }),
    key: "go-home",
    icon: render_icon(HomeOutline),
  },
  {
    label: () =>
      h(
        RouterLink,
        { to: { name: "general_config" } },
        { default: () => "General Configuration" }
      ),
    key: "go-general-config",
    icon: render_icon(SettingsOutline),
  },
  {
    label: "Device Configuration",
    key: "go-config",
    icon: render_icon(AppsOutline),
    children: [
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "data_manager_config" } },
            { default: () => "Data Manager" }
          ),
        key: "go-data-manager",
        icon: render_icon(HardwareChipOutline),
      },
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "inverter_config" } },
            { default: () => "Inverters" }
          ),
        key: "go-inverters",
        icon: render_icon(BatteryChargingOutline),
      },
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "solar_inverter_config" } },
            { default: () => "Solar Inverter" }
          ),
        key: "go-solar-inverter",
        icon: render_icon(SunnyOutline),
      },
    ],
  },
  {
    label: "Mode Specific Configuration",
    key: "go-config",
    icon: render_icon(NewspaperOutline),
    children: [
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "manual_config" } },
            { default: () => "Manual Mode" }
          ),
        key: "go-manual",
        icon: render_icon(HandLeftOutline),
      },
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "static_schedule_config" } },
            { default: () => "Static Schedule Mode" }
          ),
        key: "go-static-schedule",
        icon: render_icon(CalendarOutline),
      },
      {
        label: () =>
          h(
            RouterLink,
            { to: { name: "dynamic_schedule_config" } },
            { default: () => "Dynamic Schedule Mode" }
          ),
        key: "go-dynamic-schedule",
        icon: render_icon(BarChartOutline),
      },
    ],
  },
  {
    label: () =>
      h(
        RouterLink,
        { to: { name: "logfiles" } },
        { default: () => "Log Files" }
      ),
    key: "go-logfiles",
    icon: render_icon(FileTrayFullOutline),
  },
]);

const toggle_running = async () => {
  loading.value = true
  await control.set_running(!control.running);
  loading.value = false
};
</script>

<template>
  <n-grid cols="6">
    <n-gi span="5">
      <n-menu :options="menu_options" mode="horizontal" responsive />
    </n-gi>
    <n-gi>
      <n-button
        :loading="loading"
        :disabled="loading"
        type="primary"
        @click="toggle_running"
        style="float: right"
      >
        <template v-if="control.running">Stop</template>
        <template v-else>Start</template>
      </n-button>
    </n-gi>
  </n-grid>

</template>
