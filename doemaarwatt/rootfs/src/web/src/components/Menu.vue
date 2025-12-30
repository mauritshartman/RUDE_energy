<script setup>
import { h, ref, onMounted, onBeforeUnmount } from 'vue';
import {
    HomeOutline, HardwareChipOutline, SettingsOutline, BatteryChargingOutline,
    CalendarOutline, NewspaperOutline, HandLeftOutline, BarChartOutline,
    AppsOutline, PlayCircleOutline, StopCircleOutline
} from '@vicons/ionicons5'
import { storeToRefs } from 'pinia';
import { NIcon, NMenu, NFloatButton } from 'naive-ui';
import { RouterLink } from 'vue-router';
import { useControlStore } from '../stores/control';
import { useConfigStore } from '../stores/config';

const control = useControlStore()
const config = useConfigStore()

const { general } = storeToRefs(config)

const render_icon = (icon) => {
    return () => h(NIcon, null, { default: () => h(icon) })
}

const menu_options = ref([
    {
        label: () => h(RouterLink, { to: { name: 'home' } }, { default: () => 'Home' }),
        key: 'go-home',
        icon: render_icon(HomeOutline),
    },
    {
        label: () => h(RouterLink, { to: { name: 'general_config' } }, { default: () => 'General Configuration' }),
        key: 'go-general-config',
        icon: render_icon(SettingsOutline),
    },
    {
        label: 'Device Configuration',
        key: 'go-config',
        icon: render_icon(AppsOutline),
        children: [
            {
                label: () => h(RouterLink, { to: { name: 'data_manager_config' } }, { default: () => 'Data Manager' }),
                key: 'go-data-manager',
                icon: render_icon(HardwareChipOutline),
            },
            {
                label: () => h(RouterLink, { to: { name: 'inverter_config' } }, { default: () => 'Inverters' }),
                key: 'go-inverters',
                icon: render_icon(BatteryChargingOutline),
            },
        ]
    },
    {
        label: 'Mode Specific Configuration',
        key: 'go-config',
        icon: render_icon(NewspaperOutline),
        children: [
            {
                label: () => h(RouterLink, { to: { name: 'manual_config' } }, { default: () => 'Manual Mode' }),
                key: 'go-manual',
                icon: render_icon(HandLeftOutline),
            },
            {
                label: () => h(RouterLink, { to: { name: 'static_schedule_config' } }, { default: () => 'Static Schedule Mode' }),
                key: 'go-static-schedule',
                icon: render_icon(CalendarOutline),
            },
            {
                label: () => h(RouterLink, { to: { name: 'dynamic_schedule_config' } }, { default: () => 'Dynamic Schedule Mode' }),
                key: 'go-dynamic-schedule',
                icon: render_icon(BarChartOutline),
            },
        ]
    },
])

const toggle_running = async () => {
    control.set_running(!control.running)
}

const timer = ref()

onMounted(async () => {
    await control.fetch_status()
    await config.fetch_config()

    console.log(`status refresh loop at ${general.value.loop_delay} seconds`)

    timer.value = setInterval(async () => {
        console.log(`periodic status fetch`)
        await control.fetch_status()
    }, general.value.loop_delay * 1000)
})

onBeforeUnmount(() => {
    clearInterval(timer.value)
    timer.value = null
})
</script>


<template>
    <n-menu :options="menu_options" mode="horizontal" responsive />

    <n-float-button
        :right="20" :top="10" :height="64" :width="64" type="primary"
        @click="toggle_running"
    >
        <n-icon size="56">
            <StopCircleOutline v-if="control.running" />
            <PlayCircleOutline v-else />
        </n-icon>
    </n-float-button>
</template>