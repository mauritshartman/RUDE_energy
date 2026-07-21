import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia } from 'pinia'
// import './style.css'
import App from './App.vue'

const pinia = createPinia()
const app = createApp(App)

// Routes are lazy-loaded so each view (and its dependencies, e.g. the chart
// libraries used on the home view) ships as a separate chunk instead of
// bloating the initial bundle.
const routes = [
    { name: 'home', path: '/', component: () => import('./components/Main.vue') },
    { name: 'energy_meter_config', path: '/config/energy_meter', component: () => import('./components/EnergyMeterConfig.vue') },
    { name: 'solar_inverters_config', path: '/config/solar_inverters', component: () => import('./components/SolarInverterConfig.vue') },
    { name: 'battery_inverters_config', path: '/config/battery_inverters', component: () => import('./components/BatteryInverterConfig.vue') },
    { name: 'general_config', path: '/config/general', component: () => import('./components/StartupMode.vue') },
    { name: 'manual_config', path: '/config/manual', component: () => import('./components/ModeManualConfig.vue') },
    { name: 'static_schedule_config', path: '/config/static', component: () => import('./components/ModeStaticConfig.vue') },
    { name: 'dynamic_schedule_config', path: '/config/dynamic', component: () => import('./components/ModeDynamicConfig.vue') },
    { name: 'logfiles', path: '/logfiles', component: () => import('./components/LogViewer.vue') },
]

const router = createRouter({
    history: createWebHistory(),
    routes,
})

app.use(pinia)
app.use(router)

app.mount('#app')
