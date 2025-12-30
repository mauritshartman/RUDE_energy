import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import App from './App.vue'
import Main from './components/Main.vue'
import InverterConfig from './components/InverterConfig.vue'
import DataManagerConfig from './components/DataManagerConfig.vue'
import ModeManualConfig from './components/ModeManualConfig.vue'
import ModeStaticConfig from './components/ModeStaticConfig.vue'
import StartupMode from './components/StartupMode.vue'

const pinia = createPinia()
const app = createApp(App)

const routes = [
    { name: 'home', path: '/', component: Main },
    { name: 'data_manager_config', path: '/config/data_manager', component: DataManagerConfig },
    { name: 'inverter_config', path: '/config/inverters', component: InverterConfig },
    { name: 'general_config', path: '/config/general', component: StartupMode },
    { name: 'manual_config', path: '/config/manual', component: ModeManualConfig },
    { name: 'static_schedule_config', path: '/config/static', component: ModeStaticConfig },
    { name: 'dynamic_schedule_config', path: '/config/dynamic', component: ModeStaticConfig },
]

const router = createRouter({
    history: createWebHistory(),
    routes,
})

app.use(pinia)
app.use(router)
app.use(naive);

app.mount('#app')
