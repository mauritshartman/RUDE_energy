import { computed } from 'vue'
import { DateTime } from 'luxon'
import { useConfigStore } from '../stores/config'

export function useTimezone() {
    const config = useConfigStore()
    const tz = computed(() => config.timezone)
    const now = () => DateTime.now().setZone(tz.value)
    return { tz, now }
}
