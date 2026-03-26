from datetime import datetime as dt, timedelta, timezone
import math
import json

import numpy as np
from scipy.optimize import linprog
from prettytable import PrettyTable

from config import DoeMaarWattConfig
from price import PriceManager


# Thresholds for batteries to consider them empty and full
# For now we trust the BMS reported SoC value
# TODO: make these an inverter setting
BATTERY_EMPTY_THRESHOLD = 0.00
BATTERY_FULL_THRESHOLD = 1.00


class DynamicScheduler:
    def __init__(self,
        cfg: DoeMaarWattConfig,
        pm: PriceManager,
    ) -> None:
        self.cfg = cfg
        self.resolution = timedelta(minutes=int(self.cfg.get_mode_dynamic_config()['resolution']))
        self.efficiency = float(self.cfg.get_mode_dynamic_config()['efficiency'])
        self.pm: PriceManager = pm

        # The schedule is a sorted list of SchedulePeriods
        self.schedule: list[SchedulePeriod] = []
        self.tz = timezone(timedelta(hours=self.cfg.timezone_offset))
        self.schedule_ts: dt = dt.now(tz=self.tz)

    def schedule_available_for(self, t: dt) -> bool:
        '''Return True if the current schedule covers the given timestamp t.'''
        if not self.schedule:
            return False
        return self.schedule[0].start_ts <= t < self.schedule[-1].end_ts

    def create_schedule(self,
        start_ts: dt,
        end_ts: dt,
        current_charge: dict[str, float],
    ):
        '''Determine the optimal schedule for the given period using linear programming.

        The schedule minimises total energy cost by charging at low-price slots and
        discharging at high-price slots, subject to battery capacity and charge/discharge
        rate constraints.

        start_ts is normalised down to the nearest resolution boundary; end_ts is
        normalised up. current_charge maps each inverter name to its current stored
        energy in Wh.
        '''
        sched_start = dt.fromtimestamp(int(start_ts.timestamp()) // self.resolution.seconds * self.resolution.seconds, start_ts.tzinfo)
        sched_end = dt.fromtimestamp(math.ceil(end_ts.timestamp() / self.resolution.seconds) * self.resolution.seconds, end_ts.tzinfo)

        h = self.resolution.total_seconds() / 3600  # slot duration in hours
        N = round((sched_end - sched_start) / self.resolution)  # number of time slots

        if N == 0:
            self.schedule = []
            return

        # Fetch price data covering the schedule window
        price_range = self.pm.get_price_range(sched_start)[:N]
        if len(price_range) < N:
            raise Exception(
                f'DynamicScheduler: insufficient price data to cover schedule window '
                f'[{sched_start}, {sched_end}] ({len(price_range)} of {N} slots available)'
            )
        prices = [pr[2] for pr in price_range]

        # Inverter parameters (only enabled inverters)
        inv_capacities       = self.cfg.get_inverter_field_map('battery_capacity')
        inv_charge_limits    = self.cfg.get_inverter_field_map('battery_charge_limit')
        inv_discharge_limits = self.cfg.get_inverter_field_map('battery_discharge_limit')
        inverters = list(inv_capacities.keys())
        M = len(inverters)

        if M == 0:  # no active inverters; so create a schedule without (dis)charging
            self.schedule = []
            for iv_start, iv_end, price in price_range:
                self.schedule.append(SchedulePeriod(iv_start, iv_end, price, self.efficiency))
            return

        # ------------------------------------------------------------------
        # LP variable layout
        # x[i*N + t]         = e[i][t] = energy in battery i at END of slot t
        # x[M*N + i*N + t]   = c[i][t] = energy charged INTO battery i in t
        # x[2*M*N + i*N + t] = d[i][t] = energy discharged FROM battery i in t
        #
        # Efficiency mu is applied asymmetrically:
        #   Charging:    drawing c/mu Wh from grid stores c Wh in battery
        #   Discharging: releasing d Wh from battery delivers d*mu Wh to grid
        # ------------------------------------------------------------------
        n_vars = M * N * 3

        def e_idx(i, t): return i * N + t
        def c_idx(i, t): return M * N + i * N + t
        def d_idx(i, t): return 2 * M * N + i * N + t

        mu = self.efficiency

        # --- Objective: minimise total grid energy cost ---
        # Charging c[i][t] Wh (battery side) draws c/mu from the grid at price[t]
        # Discharging d[i][t] Wh (battery side) delivers d*mu to the grid at price[t]
        obj = np.zeros(n_vars)
        for i in range(M):
            for t in range(N):
                obj[c_idx(i, t)] =  prices[t] / (mu * 1000.0)
                obj[d_idx(i, t)] = -prices[t] * mu / 1000.0

        # --- Bounds: SoC limits per inverter + non-negative charge/discharge ---
        e_min = {inv: inv_capacities[inv] * BATTERY_EMPTY_THRESHOLD for inv in inverters}
        e_max = {inv: inv_capacities[inv] * BATTERY_FULL_THRESHOLD  for inv in inverters}
        bounds = (
            [(e_min[inverters[i]], e_max[inverters[i]]) for i in range(M) for _ in range(N)]
            + [(0.0, inv_charge_limits[inverters[i]] * h)    for i in range(M) for _ in range(N)]
            + [(0.0, inv_discharge_limits[inverters[i]] * h) for i in range(M) for _ in range(N)]
        )

        # --- Equality constraints: battery energy balance per slot ---
        # e[i][t] - e[i][t-1] - c[i][t] + d[i][t] = 0  (t > 0)
        # e[i][0]              - c[i][0]  + d[i][0] = e0 (t = 0)
        n_eq = M * N
        A_eq = np.zeros((n_eq, n_vars))
        b_eq = np.zeros(n_eq)

        row = 0
        for i, inv in enumerate(inverters):
            e0 = current_charge[inv]  # might raise KeyError if no initial charge is provided for inverter inv
            for t in range(N):
                A_eq[row, e_idx(i, t)] =  1.0
                A_eq[row, c_idx(i, t)] = -1.0
                A_eq[row, d_idx(i, t)] =  1.0
                if t == 0:
                    b_eq[row] = e0
                else:
                    A_eq[row, e_idx(i, t - 1)] = -1.0
                    b_eq[row] = 0.0
                row += 1

        # --- Solve ---
        result = linprog(obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method='highs')
        if not result.success:
            raise Exception(f'DynamicScheduler: LP solve failed: {result.message}')

        x = result.x

        # --- Build SchedulePeriod list ---
        self.schedule = []
        for t, (iv_start, iv_end, price) in enumerate(price_range):
            sp = SchedulePeriod(iv_start, iv_end, price, self.efficiency)
            sp.start_charge = {}
            sp.end_charge = {}
            for i, inv in enumerate(inverters):
                e0 = current_charge[inv]
                sp.start_charge[inv] = x[e_idx(i, t - 1)] if t > 0 else e0
                sp.end_charge[inv]   = x[e_idx(i, t)]
            self.schedule.append(sp)

        self.schedule_ts = dt.now(tz=self.tz)

    def get_PBapp_inverters(self, ts: dt) -> dict[str, float]:
        '''Asserting that a schedule has been created, get the PBapp values for each inverter for the given time ts
        '''
        assert len(self.schedule) > 0, 'unable to get_PBapp_inverters when schedule not yet set'
        assert self.schedule[0].start_ts <= ts and ts < self.schedule[-1].end_ts, 'requested time outside schedule range'

        for sp in self.schedule:
            if sp.start_ts <= ts and ts < sp.end_ts:
                return sp.PBapp_inverters

        raise Exception(f'get_PBapp_inverters(): requested time {ts} could not be found in schedule {self.schedule}')

    def schedule_to_string(self) -> str:
        if not self.schedule:
            return 'Schedule is empty.'

        inv_names = list(self.schedule[0].end_charge.keys()) if self.schedule[0].end_charge else []

        table = PrettyTable()
        table.field_names = (
            ['#', 'Start', 'End', 'Price (€/kWh)']
            + [f'{inv}\nstart (Wh)' for inv in inv_names]
            + [f'{inv}\nend (Wh)'   for inv in inv_names]
            + [f'{inv}\nPBapp (W)'  for inv in inv_names]
        )

        total_cost = 0.0
        for slot_idx, sp in enumerate(self.schedule):
            pbapp = sp.PBapp_inverters
            total_cost += sp.cost
            table.add_row(
                [
                    slot_idx,
                    sp.start_ts.strftime('%H:%M'),
                    sp.end_ts.strftime('%H:%M'),
                    f'{sp.price:.4f}',
                ]
                + [f'{sp.start_charge[inv]:.0f}' for inv in inv_names]
                + [f'{sp.end_charge[inv]:.0f}'   for inv in inv_names]
                + [f'{-pbapp[inv]:+.0f}'          for inv in inv_names]
            )

        return str(table) + f'\nTotal projected cost / revenue: {total_cost:+.4f} € (negative = revenue)'


class SchedulePeriod:
    def __init__(self,
        start_ts: dt,
        end_ts: dt,
        price: float,
        efficiency: float,
    ) -> None:
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.price = price  # in kWh
        self.efficiency = efficiency  # [0 - 1]

        # duration of this period expressed in hours:
        self.duration_hours = (self.end_ts - self.start_ts) / timedelta(hours=1)

        # planned charge (Wh) of each inverter at the start and end of this schedule period:
        self.start_charge: dict[str, float] = {}
        self.end_charge: dict[str, float] = {}

    @property
    def cost(self) -> float:
        total = 0.0
        for inv, end_charge in self.end_charge.items():
            delta = end_charge - self.start_charge[inv]  # Wh, battery side
            if delta >= 0:  # charging: grid draws more than what is stored
                total += delta / self.efficiency / 1000.0 * self.price
            else:  # discharging: grid receives less than what leaves the battery
                total += delta * self.efficiency / 1000.0 * self.price
        return total

    def to_dict(self) -> dict:
        return {
            'start_ts': self.start_ts.isoformat(),
            'end_ts': self.end_ts.isoformat(),
            'price': self.price,
            'cost': self.cost,
            'start_charge': self.start_charge,
            'end_charge': self.end_charge,
            'PBapp_inverters': self.PBapp_inverters,
        }

    @property
    def PBapp_inverters(self) -> dict[str, float]:
        ret = {}
        for inv, charge in self.end_charge.items():
            charge_delta = charge - self.start_charge[inv]  # diff in Wh
            ret[inv] = charge_delta / self.duration_hours  # charge/discharge power in Watts
        return ret


class SchedulePeriodEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, SchedulePeriod):
            return o.to_dict()
        if isinstance(o, dt):
            return o.isoformat()
        return super().default(o)


if __name__ == '__main__':
    import asyncio
    from datetime import timezone
    from prettytable import PrettyTable
    from logger import Logger, LogLevel

    async def main():
        log = Logger(loglevel=LogLevel.DEBUG, filedir='logs', rotate=10)
        cfg = DoeMaarWattConfig(log)

        tz = timezone(timedelta(hours=cfg.timezone_offset))
        now = dt.now(tz)
        start_ts = now
        end_ts   = now + timedelta(hours=27)

        print(f'\n=== DynamicScheduler test ===')
        print(f'Schedule window : [{start_ts.strftime("%Y-%m-%d %H:%M %Z")} — {end_ts.strftime("%Y-%m-%d %H:%M %Z")}]')
        print(f'Resolution      : {cfg.get_mode_dynamic_config()["resolution"]} minutes')

        pm = PriceManager(cfg, log)
        print(f'\nFetching prices ...')
        await pm.fetch_prices()
        price_range = pm.get_price_range(start_ts)
        print(f'Available prices: {len(price_range)} slots  [{price_range[0][0].strftime("%H:%M")} — {price_range[-1][1].strftime("%H:%M")}]')

        # Use 50 % state-of-charge as the starting point for each configured inverter
        inv_capacities = cfg.get_inverter_field_map('battery_capacity')
        # current_charge = {inv: cap * 0.5 for inv, cap in inv_capacities.items()}
        current_charge = {
            'inv1': 0.64 * 64000,
            'inv2': 0.78 * 64000,
            'inv3': 0.80 * 64000,
        }

        print(f'\nConfigured inverters:')
        for inv, cap in inv_capacities.items():
            print(f'  {inv}: capacity={cap} Wh, starting charge={current_charge[inv]:.0f} Wh (50 %)')

        scheduler = DynamicScheduler(cfg, pm)

        print(f'\nSolving LP ...')
        scheduler.create_schedule(start_ts, end_ts, current_charge)
        print(f'Schedule created: {len(scheduler.schedule)} periods')

        print(scheduler.schedule_to_string())

    asyncio.run(main())