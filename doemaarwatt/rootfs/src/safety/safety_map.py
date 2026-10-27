from .battery_soc_limits import DESCRIPTION_BatterySoCLimitsMixin
from .battery_charge_limits import DESCRIPTION_BatteryChargeLimitsMixin
from .main_fuse_protection import DESCRIPTION_MainFuseProtectionMixin

'''Safety check priorities (lower is more important)
0 - 99 range: general safety checks
100 - 999 range: preferred behavior
1000 - 10_000 range: mode specific behavior
'''
SAFETY_CHECK_PRIORITIES: dict[str, int] = {
    'ensure_main_fuse_protection': 10,
    'ensure_battery_soc_limits': 100,
    'ensure_battery_charge_limits': 101,
}

'''Safety checks that are always applied, whether they are enabled in the configuration or not. Protecting the
main fuse is what stands between a computed schedule and a tripped main circuit breaker, so it is not left to
a setting: without it the controller can command currents beyond what the grid connection can carry. These
checks are still listed in the configuration (and shown in the web UI) so it is visible that they are applied.
'''
ALWAYS_ON_SAFETY_CHECKS: set[str] = {
    'ensure_main_fuse_protection',
}

SAFETY_CHECK_DESCRIPTIONS = {
    'ensure_main_fuse_protection': DESCRIPTION_MainFuseProtectionMixin.replace('\n', ' ').strip(),
    'ensure_battery_soc_limits': DESCRIPTION_BatterySoCLimitsMixin.replace('\n', ' ').strip(),
    'ensure_battery_charge_limits': DESCRIPTION_BatteryChargeLimitsMixin.replace('\n', ' ').strip(),
}
